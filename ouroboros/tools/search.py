"""Web search tool."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from ouroboros.tools.registry import ToolContext, ToolEntry


def _duckduckgo_fallback(query: str, ctx: ToolContext) -> str:
    if ctx.emit_progress_fn:
        ctx.emit_progress_fn("⚠️ OpenAI search failed. Falling back to DuckDuckGo.")
        
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
            if not results:
                return json.dumps({"answer": "(no results found via DuckDuckGo)"}, ensure_ascii=False)
            
            # Format results into a readable string
            formatted_results = []
            for i, r in enumerate(results, 1):
                formatted_results.append(f"{i}. {r.get('title', 'No Title')}\n   URL: {r.get('href', 'No URL')}\n   Snippet: {r.get('body', 'No snippet')}")
                
            return "Search Results (DuckDuckGo Fallback):\n\n" + "\n\n".join(formatted_results)
    except ImportError:
        return json.dumps({"error": "duckduckgo-search package not installed and OpenAI failed."})
    except Exception as e:
        return json.dumps({"error": f"DuckDuckGo fallback failed: {repr(e)}"}, ensure_ascii=False)

def _web_search(ctx: ToolContext, query: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return _duckduckgo_fallback(query, ctx)
        
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp = client.responses.create(
            model=os.environ.get("OUROBOROS_WEBSEARCH_MODEL", "gpt-5"),
            tools=[{"type": "web_search"}],
            tool_choice="auto",
            input=query,
        )
        d = resp.model_dump()
        text = ""
        for item in d.get("output", []) or []:
            if item.get("type") == "message":
                for block in item.get("content", []) or []:
                    if block.get("type") in ("output_text", "text"):
                        text += block.get("text", "")
        return json.dumps({"answer": text or "(no answer)"}, ensure_ascii=False, indent=2)
    except Exception as e:
        # Fallback on any error (like rate limit, billing inactive, connection error)
        return _duckduckgo_fallback(query, ctx)


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("web_search", {
            "name": "web_search",
            "description": "Search the web via OpenAI Responses API with DuckDuckGo fallback. Returns text results.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"},
            }, "required": ["query"]},
        }, _web_search),
    ]
