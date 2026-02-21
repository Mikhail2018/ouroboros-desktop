"""
Safety Agent — A dual-layer LLM security supervisor.

This module intercepts potentially dangerous tool calls (shell, code edit, git)
and passes them through a light model. If flagged, it passes through a heavy model.
Returns (True, None) if safe, or (False, ErrorMessage) if blocked.
"""

import logging
import json
import os
import pathlib
from typing import Tuple, Dict, Any

from ouroboros.llm import LLMClient, DEFAULT_LIGHT_MODEL
from supervisor.state import update_budget_from_usage

log = logging.getLogger(__name__)

def _get_safety_prompt() -> str:
    """Load the safety system prompt from prompts/SAFETY.md."""
    # Assuming this runs with repo_dir as cwd or we can resolve it relative to this file
    prompt_path = pathlib.Path(__file__).parent.parent / "prompts" / "SAFETY.md"
    try:
        return prompt_path.read_text(encoding="utf-8")
    except Exception as e:
        log.error(f"Failed to read SAFETY.md: {e}")
        # Fallback to a basic prompt if the file is missing
        return "You are a security supervisor. Block any destructive commands or attempts to modify BIBLE.md. Respond with JSON: {\"status\": \"SAFE\"|\"DANGEROUS\", \"reason\": \"...\"}"

def _build_check_prompt(tool_name: str, arguments: Dict[str, Any]) -> str:
    args_json = json.dumps(arguments, indent=2)
    return f"Proposed tool call:\nTool: {tool_name}\nArguments:\n```json\n{args_json}\n```\n\nIs this safe?"


def check_safety(tool_name: str, arguments: Dict[str, Any]) -> Tuple[bool, str]:
    """Check if a tool call is safe to execute."""
    
    # We only care about mutative or shell-access tools
    if tool_name not in ["run_shell", "claude_code_edit", "repo_write_commit", "repo_commit", "drive_write"]:
        return True, ""
        
    prompt = _build_check_prompt(tool_name, arguments)
    client = LLMClient()
    
    # Fast check
    try:
        light_model = os.environ.get("OUROBOROS_MODEL_LIGHT", DEFAULT_LIGHT_MODEL)
        log.info(f"Running fast safety check on {tool_name} using {light_model}")
        msg, usage = client.chat(
            messages=[
                {"role": "system", "content": _get_safety_prompt()},
                {"role": "user", "content": prompt}
            ],
            model=light_model,
        )
        text = msg.get("content") or ""
        
        if usage:
            update_budget_from_usage(usage)
            
        try:
            # Try to parse JSON from the response. LLM might wrap it in markdown.
            clean_text = text.replace("```json", "").replace("```", "").strip()
            result = json.loads(clean_text)
            
            if result.get("status") == "SAFE":
                return True, ""
                
            fast_reason = result.get("reason", "Unknown danger")
            log.warning(f"Fast safety check flagged {tool_name}: {fast_reason}")
            
        except json.JSONDecodeError:
            log.warning(f"Fast safety check returned invalid JSON: {text}. Proceeding to heavy check.")
            fast_reason = "Invalid JSON response from fast check."
            
    except Exception as e:
        log.error(f"Fast safety check failed: {e}. Proceeding to heavy check.")
        fast_reason = str(e)
        
    # Deep check (if fast check flagged it or failed)
    try:
        heavy_model = os.environ.get("OUROBOROS_MODEL_CODE", os.environ.get("OUROBOROS_MODEL", "anthropic/claude-sonnet-4.6"))
        log.info(f"Running deep safety check on {tool_name} using {heavy_model}")
        msg, usage = client.chat(
            messages=[
                {"role": "system", "content": _get_safety_prompt() + "\nTake a deep breath and think carefully. Is this actually malicious, or just a normal development command?"},
                {"role": "user", "content": prompt}
            ],
            model=heavy_model,
        )
        text = msg.get("content") or ""
        
        if usage:
            update_budget_from_usage(usage)
            
        try:
            clean_text = text.replace("```json", "").replace("```", "").strip()
            result = json.loads(clean_text)
            
            if result.get("status") == "SAFE":
                log.info(f"Deep check cleared {tool_name}. Proceeding.")
                return True, ""
                
            heavy_reason = result.get("reason", "Unknown danger")
            log.error(f"Deep safety check blocked {tool_name}: {heavy_reason}")
            return False, f"⚠️ SAFETY_VIOLATION: The Safety Supervisor blocked this command.\nReason: {heavy_reason}\n\nYou must find a different, safer approach to achieve your goal."
            
        except json.JSONDecodeError:
            log.error(f"Deep safety check returned invalid JSON: {text}")
            return False, "⚠️ SAFETY_VIOLATION: Safety Supervisor failed to parse JSON."
            
    except Exception as e:
        log.error(f"Deep safety check failed: {e}")
        return False, f"⚠️ SAFETY_VIOLATION: Safety check failed with error: {e}"
