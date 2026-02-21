"""
Ouroboros Desktop App — Flet UI & Main Launcher
"""

import asyncio
import json
import logging
import os
import pathlib
import shutil
import sys
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
import flet as ft

# ---------------------------------------------------------------------------
# Setup Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger(__name__)

APP_VERSION = "6.2.0"
APP_START = time.time()

# ---------------------------------------------------------------------------
# Paths and Bootstrapping
# ---------------------------------------------------------------------------
HOME = pathlib.Path.home()
APP_ROOT = HOME / "Documents" / "Ouroboros"
REPO_DIR = APP_ROOT / "repo"
DATA_DIR = APP_ROOT / "data"
SETTINGS_PATH = DATA_DIR / "settings.json"

MODELS = [
    "anthropic/claude-sonnet-4.6",
    "anthropic/claude-opus-4",
    "google/gemini-3-pro-preview",
    "google/gemini-2.5-flash",
    "openai/gpt-5",
    "openai/o3-mini",
    "meta-llama/llama-4-70b",
]

def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "OPENROUTER_API_KEY": "",
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "OUROBOROS_MODEL": "anthropic/claude-sonnet-4.6",
        "OUROBOROS_MODEL_CODE": "anthropic/claude-sonnet-4.6",
        "OUROBOROS_MODEL_LIGHT": "google/gemini-3-pro-preview",
        "OUROBOROS_MAX_WORKERS": 5,
        "TOTAL_BUDGET": 10.0,
        "OUROBOROS_SOFT_TIMEOUT_SEC": 600,
        "OUROBOROS_HARD_TIMEOUT_SEC": 1800,
    }

def save_settings(settings: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")

def bootstrap_repo():
    """Copy the bundled codebase to the local repo directory on first run."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    if not REPO_DIR.exists():
        log.info(f"First run detected. Bootstrapping repository to {REPO_DIR}...")
        
        # In a bundled app, the source code is relative to sys._MEIPASS or __file__
        if getattr(sys, 'frozen', False):
            bundle_dir = pathlib.Path(sys._MEIPASS)
        else:
            bundle_dir = pathlib.Path(__file__).parent
            
        # Copy everything except the repo itself and data dirs to avoid recursion if run locally
        shutil.copytree(bundle_dir, REPO_DIR, ignore=shutil.ignore_patterns("repo", "data", "build", "dist", ".git", "__pycache__", "venv", ".venv"))
        
        # Generate WORLD.md
        from ouroboros.world_profiler import generate_world_profile
        memory_dir = DATA_DIR / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        generate_world_profile(str(memory_dir / "WORLD.md"))

        # Initialize Git
        import dulwich.repo
        from supervisor.git_ops import git_capture
        repo = dulwich.repo.Repo.init(str(REPO_DIR))
        
        subprocess.run(["git", "config", "user.name", "Ouroboros"], cwd=str(REPO_DIR), check=True)
        subprocess.run(["git", "config", "user.email", "ouroboros@local.mac"], cwd=str(REPO_DIR), check=True)
        subprocess.run(["git", "add", "-A"], cwd=str(REPO_DIR), check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit from app bundle"], cwd=str(REPO_DIR), check=False)
        subprocess.run(["git", "branch", "-M", "ouroboros"], cwd=str(REPO_DIR), check=False)
        subprocess.run(["git", "branch", "ouroboros-stable"], cwd=str(REPO_DIR), check=False)
        log.info("Bootstrap complete.")

# ---------------------------------------------------------------------------
# Background Supervisor Loop
# ---------------------------------------------------------------------------
SUPERVISOR_THREAD = None
CHAT_BRIDGE = None

def run_supervisor(settings: dict):
    global CHAT_BRIDGE
    
    # Set environment variables
    os.environ["OPENROUTER_API_KEY"] = str(settings.get("OPENROUTER_API_KEY", ""))
    os.environ["OPENAI_API_KEY"] = str(settings.get("OPENAI_API_KEY", ""))
    os.environ["ANTHROPIC_API_KEY"] = str(settings.get("ANTHROPIC_API_KEY", ""))
    os.environ["OUROBOROS_MODEL"] = str(settings.get("OUROBOROS_MODEL", "anthropic/claude-sonnet-4.6"))
    os.environ["OUROBOROS_MODEL_CODE"] = str(settings.get("OUROBOROS_MODEL_CODE", "anthropic/claude-sonnet-4.6"))
    os.environ["OUROBOROS_MODEL_LIGHT"] = str(settings.get("OUROBOROS_MODEL_LIGHT", "google/gemini-3-pro-preview"))
    os.environ["TOTAL_BUDGET"] = str(settings.get("TOTAL_BUDGET", 10.0))
    
    # Initialize Core Modules
    import queue as _queue_mod
    from supervisor.telegram import LocalChatBridge, init as telegram_init
    CHAT_BRIDGE = LocalChatBridge()
    
    telegram_init(
        drive_root=DATA_DIR,
        total_budget_limit=float(settings.get("TOTAL_BUDGET", 10.0)),
        budget_report_every=10,
        tg_client=CHAT_BRIDGE,
    )
    
    from supervisor.state import init as state_init, init_state, load_state, save_state, append_jsonl, update_budget_from_usage, rotate_chat_log_if_needed
    state_init(DATA_DIR, float(settings.get("TOTAL_BUDGET", 10.0)))
    init_state()
    
    from supervisor.git_ops import init as git_ops_init, ensure_repo_present, safe_restart
    git_ops_init(
        repo_dir=REPO_DIR, drive_root=DATA_DIR, remote_url="",
        branch_dev="ouroboros", branch_stable="ouroboros-stable",
    )
    
    ensure_repo_present()
    ok, msg = safe_restart(reason="bootstrap", unsynced_policy="rescue_and_reset")
    if not ok:
        log.error(f"Supervisor Bootstrap failed: {msg}")
    
    from supervisor.queue import enqueue_task, enforce_task_timeouts, enqueue_evolution_task_if_needed, persist_queue_snapshot, restore_pending_from_snapshot, cancel_task_by_id, queue_review_task, sort_pending
    from supervisor.workers import init as workers_init, get_event_q, WORKERS, PENDING, RUNNING, spawn_workers, kill_workers, assign_tasks, ensure_workers_healthy, handle_chat_direct, _get_chat_agent, auto_resume_after_restart
    
    max_workers = int(settings.get("OUROBOROS_MAX_WORKERS", 5))
    soft_timeout = int(settings.get("OUROBOROS_SOFT_TIMEOUT_SEC", 600))
    hard_timeout = int(settings.get("OUROBOROS_HARD_TIMEOUT_SEC", 1800))
    
    workers_init(
        repo_dir=REPO_DIR, drive_root=DATA_DIR, max_workers=max_workers,
        soft_timeout=soft_timeout, hard_timeout=hard_timeout,
        total_budget_limit=float(settings.get("TOTAL_BUDGET", 10.0)),
        branch_dev="ouroboros", branch_stable="ouroboros-stable",
    )
    
    from supervisor.events import dispatch_event
    import types
    
    kill_workers()
    spawn_workers(max_workers)
    restored_pending = restore_pending_from_snapshot()
    persist_queue_snapshot(reason="startup")
    
    from supervisor.telegram import send_with_budget
    
    if restored_pending > 0:
        st_boot = load_state()
        if st_boot.get("owner_chat_id"):
            send_with_budget(int(st_boot["owner_chat_id"]), f"♻️ Restored pending queue from snapshot: {restored_pending} tasks.")
            
    auto_resume_after_restart()
    
    from ouroboros.consciousness import BackgroundConsciousness
    def _get_owner_chat_id() -> Optional[int]:
        try:
            st = load_state()
            cid = st.get("owner_chat_id")
            return int(cid) if cid else None
        except Exception:
            return None

    _consciousness = BackgroundConsciousness(
        drive_root=DATA_DIR,
        repo_dir=REPO_DIR,
        event_queue=get_event_q(),
        owner_chat_id_fn=_get_owner_chat_id,
    )
    
    try:
        _consciousness.start()
    except Exception:
        pass

    _event_ctx = types.SimpleNamespace(
        DRIVE_ROOT=DATA_DIR,
        REPO_DIR=REPO_DIR,
        BRANCH_DEV="ouroboros",
        BRANCH_STABLE="ouroboros-stable",
        TG=CHAT_BRIDGE,
        WORKERS=WORKERS,
        PENDING=PENDING,
        RUNNING=RUNNING,
        MAX_WORKERS=max_workers,
        send_with_budget=send_with_budget,
        load_state=load_state,
        save_state=save_state,
        update_budget_from_usage=update_budget_from_usage,
        append_jsonl=append_jsonl,
        enqueue_task=enqueue_task,
        cancel_task_by_id=cancel_task_by_id,
        queue_review_task=queue_review_task,
        persist_queue_snapshot=persist_queue_snapshot,
        safe_restart=safe_restart,
        kill_workers=kill_workers,
        spawn_workers=spawn_workers,
        sort_pending=sort_pending,
        consciousness=_consciousness,
    )
    
    # ----------------------------
    # Main Supervisor Loop
    # ----------------------------
    offset = 0
    while True:
        rotate_chat_log_if_needed(DATA_DIR)
        ensure_workers_healthy()

        event_q = get_event_q()
        while True:
            try:
                evt = event_q.get_nowait()
            except _queue_mod.Empty:
                break
            dispatch_event(evt, _event_ctx)

        enforce_task_timeouts()
        enqueue_evolution_task_if_needed()
        assign_tasks()
        persist_queue_snapshot(reason="main_loop")

        updates = CHAT_BRIDGE.get_updates(offset=offset, timeout=1)
        for upd in updates:
            offset = int(upd["update_id"]) + 1
            msg = upd.get("message") or {}
            if not msg:
                continue

            chat_id = 1
            user_id = 1
            text = str(msg.get("text") or "")
            now_iso = datetime.now(timezone.utc).isoformat()

            st = load_state()
            if st.get("owner_id") is None:
                st["owner_id"] = user_id
                st["owner_chat_id"] = chat_id
                st["last_owner_message_at"] = now_iso
                save_state(st)
                from supervisor.telegram import log_chat
                log_chat("in", chat_id, user_id, text)
                send_with_budget(chat_id, "✅ Owner registered. Ouroboros online.")
                continue

            from supervisor.telegram import log_chat
            log_chat("in", chat_id, user_id, text)
            st["last_owner_message_at"] = now_iso
            save_state(st)

            if not text:
                continue

            # Intercept supervisor commands
            lowered = text.strip().lower()
            if lowered.startswith("/panic"):
                send_with_budget(chat_id, "🛑 PANIC: stopping everything now.")
                kill_workers()
                os._exit(1)
            elif lowered.startswith("/restart"):
                send_with_budget(chat_id, "♻️ Restarting (soft).")
                ok, restart_msg = safe_restart(reason="owner_restart", unsynced_policy="rescue_and_reset")
                if not ok:
                    send_with_budget(chat_id, f"⚠️ Restart cancelled: {restart_msg}")
                    continue
                kill_workers()
                os.execv(sys.executable, [sys.executable, __file__])
            elif lowered.startswith("/review"):
                queue_review_task(reason="owner:/review", force=True)
                continue
            elif lowered.startswith("/evolve"):
                parts = lowered.split()
                action = parts[1] if len(parts) > 1 else "on"
                turn_on = action not in ("off", "stop", "0")
                st2 = load_state()
                st2["evolution_mode_enabled"] = bool(turn_on)
                save_state(st2)
                if not turn_on:
                    PENDING[:] = [t for t in PENDING if str(t.get("type")) != "evolution"]
                    sort_pending()
                    persist_queue_snapshot(reason="evolve_off")
                state_str = "ON" if turn_on else "OFF"
                send_with_budget(chat_id, f"🧬 Evolution: {state_str}")
                continue
            elif lowered.startswith("/bg"):
                parts = lowered.split()
                action = parts[1] if len(parts) > 1 else "status"
                if action in ("start", "on", "1"):
                    result = _consciousness.start()
                    send_with_budget(chat_id, f"🧠 {result}")
                elif action in ("stop", "off", "0"):
                    result = _consciousness.stop()
                    send_with_budget(chat_id, f"🧠 {result}")
                else:
                    bg_status = "running" if _consciousness.is_running else "stopped"
                    send_with_budget(chat_id, f"🧠 Background consciousness: {bg_status}")
                continue
            elif lowered.startswith("/status"):
                from supervisor.state import status_text
                status = status_text(WORKERS, PENDING, RUNNING, soft_timeout, hard_timeout)
                send_with_budget(chat_id, status, force_budget=True)
                continue

            _consciousness.inject_observation(f"Owner message: {text[:100]}")
            agent = _get_chat_agent()

            if agent._busy:
                agent.inject_message(text)
            else:
                _consciousness.pause()
                def _run_task_and_resume(cid, txt):
                    try:
                        handle_chat_direct(cid, txt, None)
                    finally:
                        _consciousness.resume()
                _t = threading.Thread(
                    target=_run_task_and_resume,
                    args=(chat_id, text),
                    daemon=True,
                )
                _t.start()

        time.sleep(0.5)

# ---------------------------------------------------------------------------
# UI Helpers
# ---------------------------------------------------------------------------
class ChatBubble(ft.Container):
    def __init__(self, text: str, is_user: bool, markdown: bool = False):
        super().__init__()
        self.padding = ft.padding.symmetric(horizontal=14, vertical=10)
        self.border_radius = ft.border_radius.all(16)
        self.margin = ft.margin.only(
            left=120 if is_user else 0,
            right=0 if is_user else 120,
            top=2,
            bottom=2,
        )
        self.bgcolor = ft.Colors.BLUE_700 if is_user else ft.Colors.with_opacity(0.12, ft.Colors.WHITE)

        label = "You" if is_user else "Ouroboros"
        label_color = ft.Colors.BLUE_200 if is_user else ft.Colors.TEAL_200

        msg_control = ft.Markdown(text, selectable=True) if markdown else ft.Text(text, size=14, selectable=True, color=ft.Colors.WHITE if is_user else ft.Colors.WHITE70)

        self.content = ft.Column(
            spacing=4,
            controls=[
                ft.Text(label, size=11, weight=ft.FontWeight.BOLD, color=label_color),
                msg_control,
            ],
        )

def status_card(title: str, value_control: ft.Control, icon: str, icon_color: str = ft.Colors.TEAL_200) -> ft.Container:
    return ft.Container(
        bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
        border_radius=12,
        padding=20,
        expand=True,
        content=ft.Column(
            spacing=8,
            controls=[
                ft.Row([
                    ft.Icon(icon, color=icon_color, size=20),
                    ft.Text(title, size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE54),
                ]),
                value_control,
            ],
        ),
    )


# ---------------------------------------------------------------------------
# Flet Application
# ---------------------------------------------------------------------------
def main(page: ft.Page):
    page.title = f"Ouroboros v{APP_VERSION}"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 1100
    page.window.height = 750
    page.padding = 0
    page.spacing = 0

    settings = load_settings()

    # CHAT PAGE
    chat_list = ft.ListView(auto_scroll=True, spacing=4, padding=20, expand=True)
    chat_input = ft.TextField(
        hint_text="Message Ouroboros...",
        border_radius=24,
        filled=True,
        expand=True,
        shift_enter=True,
    )

    def send_message(_e):
        text = chat_input.value
        if not text or not text.strip():
            return
        chat_input.value = ""
        chat_list.controls.append(ChatBubble(text, is_user=True))
        page.update()
        
        if CHAT_BRIDGE:
            CHAT_BRIDGE.ui_send(text)

    chat_input.on_submit = send_message
    send_btn = ft.IconButton(icon=ft.Icons.SEND_ROUNDED, icon_color=ft.Colors.BLUE_400, on_click=send_message)

    chat_page = ft.Column(
        expand=True,
        controls=[
            ft.Container(
                bgcolor=ft.Colors.with_opacity(0.03, ft.Colors.WHITE),
                padding=ft.padding.symmetric(horizontal=20, vertical=12),
                content=ft.Row([
                    ft.Icon(ft.Icons.SMART_TOY_OUTLINED, color=ft.Colors.TEAL_200),
                    ft.Text("Chat", size=16, weight=ft.FontWeight.BOLD),
                    ft.Container(expand=True),
                    ft.Container(
                        bgcolor=ft.Colors.GREEN_900,
                        border_radius=12,
                        padding=ft.padding.symmetric(horizontal=10, vertical=4),
                        content=ft.Text("Online", size=11, color=ft.Colors.GREEN_200),
                    ),
                ]),
            ),
            chat_list,
            ft.Container(
                padding=ft.padding.only(left=16, right=16, bottom=16, top=8),
                content=ft.Row(controls=[chat_input, send_btn], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ),
        ],
    )

    # DASHBOARD PAGE
    uptime_text = ft.Text("0s", size=22, weight=ft.FontWeight.BOLD)
    workers_text = ft.Text("...", size=16, weight=ft.FontWeight.BOLD)
    workers_bar = ft.ProgressBar(value=0.0, color=ft.Colors.TEAL_400, width=200)
    budget_text = ft.Text("...", size=16, weight=ft.FontWeight.BOLD)
    budget_bar = ft.ProgressBar(value=0.0, color=ft.Colors.AMBER_400, width=200)
    branch_text = ft.Text("ouroboros", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_300)
    log_list = ft.ListView(auto_scroll=True, spacing=2, height=140, padding=10)

    evo_switch = ft.Switch(label="Evolution Mode", value=True)
    bg_switch = ft.Switch(label="Background Consciousness", value=True)
    consciousness_dot = ft.Container(
        width=10, height=10, border_radius=5,
        bgcolor=ft.Colors.TEAL_400,
        animate=ft.Animation(1000, ft.AnimationCurve.EASE_IN_OUT),
    )

    def on_evo_change(e):
        if CHAT_BRIDGE:
            action = "start" if evo_switch.value else "stop"
            CHAT_BRIDGE.ui_send(f"/evolve {action}")

    def on_bg_change(e):
        if CHAT_BRIDGE:
            action = "start" if bg_switch.value else "stop"
            CHAT_BRIDGE.ui_send(f"/bg {action}")

    evo_switch.on_change = on_evo_change
    bg_switch.on_change = on_bg_change

    def on_review_click(_e):
        if CHAT_BRIDGE:
            CHAT_BRIDGE.ui_send("/review")
        page.open(ft.SnackBar(ft.Text("Review queued via command"), duration=2000))
        page.update()

    def on_restart_click(_e):
        if CHAT_BRIDGE:
            CHAT_BRIDGE.ui_send("/restart")
        page.open(ft.SnackBar(ft.Text("Sent restart command to supervisor"), duration=2000))
        page.update()

    def on_panic_click(_e):
        def close_dialog(_e2):
            dialog.open = False
            page.update()
        def confirm_panic(_e2):
            if CHAT_BRIDGE:
                CHAT_BRIDGE.ui_send("/panic")
            dialog.open = False
            page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("PANIC STOP"),
            content=ft.Text("Are you sure? All workers will be killed immediately."),
            actions=[
                ft.TextButton("Cancel", on_click=close_dialog),
                ft.TextButton("PANIC", on_click=confirm_panic, style=ft.ButtonStyle(color=ft.Colors.RED_400)),
            ],
        )
        page.open(dialog)
        page.update()

    dashboard_page = ft.Column(
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Container(
                bgcolor=ft.Colors.with_opacity(0.03, ft.Colors.WHITE),
                padding=ft.padding.symmetric(horizontal=20, vertical=12),
                content=ft.Row([
                    ft.Icon(ft.Icons.DASHBOARD_OUTLINED, color=ft.Colors.TEAL_200),
                    ft.Text("Dashboard", size=16, weight=ft.FontWeight.BOLD),
                    ft.Container(expand=True),
                ]),
            ),
            ft.Container(
                padding=20,
                content=ft.Column(
                    spacing=20,
                    controls=[
                        ft.Text(f"Ouroboros v{APP_VERSION}", size=24, weight=ft.FontWeight.BOLD),

                        ft.ResponsiveRow([
                            ft.Container(col={"sm": 6, "md": 3}, content=status_card("UPTIME", uptime_text, ft.Icons.TIMER_OUTLINED)),
                            ft.Container(col={"sm": 6, "md": 3}, content=status_card("WORKERS", ft.Column([workers_text, workers_bar], spacing=6), ft.Icons.MEMORY)),
                            ft.Container(col={"sm": 6, "md": 3}, content=status_card("BUDGET", ft.Column([budget_text, budget_bar], spacing=6), ft.Icons.ATTACH_MONEY, icon_color=ft.Colors.AMBER_400)),
                            ft.Container(col={"sm": 6, "md": 3}, content=status_card("BRANCH", ft.Row([ft.Container(width=8, height=8, border_radius=4, bgcolor=ft.Colors.GREEN_400), branch_text], spacing=8), ft.Icons.ACCOUNT_TREE_OUTLINED, icon_color=ft.Colors.GREEN_300)),
                        ]),

                        ft.Divider(height=1, color=ft.Colors.WHITE10),

                        ft.Text("Controls", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE54),
                        ft.Row([evo_switch, ft.Container(width=20), bg_switch, consciousness_dot], wrap=True),

                        ft.Row([
                            ft.ElevatedButton("Force Review", icon=ft.Icons.RATE_REVIEW_OUTLINED, on_click=on_review_click),
                            ft.ElevatedButton("Restart Agent", icon=ft.Icons.REFRESH, on_click=on_restart_click),
                            ft.ElevatedButton("Panic Stop", icon=ft.Icons.DANGEROUS_OUTLINED, color=ft.Colors.RED_300, on_click=on_panic_click),
                        ], wrap=True),

                        ft.Divider(height=1, color=ft.Colors.WHITE10),
                        ft.Text("Live Log", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE54),
                        ft.Container(bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.WHITE), border_radius=8, content=log_list),
                    ],
                ),
            ),
        ],
    )

    # SETTINGS PAGE
    api_key_field = ft.TextField(label="OpenRouter API Key", value=settings.get("OPENROUTER_API_KEY", ""), password=True, can_reveal_password=True, width=500)
    openai_key_field = ft.TextField(label="OpenAI API Key (optional)", value=settings.get("OPENAI_API_KEY", ""), password=True, can_reveal_password=True, width=500)
    anthropic_key_field = ft.TextField(label="Anthropic API Key (optional)", value=settings.get("ANTHROPIC_API_KEY", ""), password=True, can_reveal_password=True, width=500)
    
    model_main = ft.Dropdown(label="Main Model", width=350, value=settings.get("OUROBOROS_MODEL"), options=[ft.dropdown.Option(m) for m in MODELS])
    model_code = ft.Dropdown(label="Code Model", width=350, value=settings.get("OUROBOROS_MODEL_CODE"), options=[ft.dropdown.Option(m) for m in MODELS])
    model_light = ft.Dropdown(label="Light Model", width=350, value=settings.get("OUROBOROS_MODEL_LIGHT"), options=[ft.dropdown.Option(m) for m in MODELS])
    
    workers_slider = ft.Slider(min=1, max=10, value=int(settings.get("OUROBOROS_MAX_WORKERS", 5)), divisions=9, label="{value}", width=350)
    budget_field = ft.TextField(label="Total Budget ($)", value=str(settings.get("TOTAL_BUDGET", 10.0)), width=200)
    
    soft_timeout_slider = ft.Slider(min=60, max=3600, value=int(settings.get("OUROBOROS_SOFT_TIMEOUT_SEC", 600)), divisions=59, label="{value}s", width=350)
    hard_timeout_slider = ft.Slider(min=120, max=7200, value=int(settings.get("OUROBOROS_HARD_TIMEOUT_SEC", 1800)), divisions=59, label="{value}s", width=350)

    def on_save(_e):
        settings.update({
            "OPENROUTER_API_KEY": api_key_field.value,
            "OPENAI_API_KEY": openai_key_field.value,
            "ANTHROPIC_API_KEY": anthropic_key_field.value,
            "OUROBOROS_MODEL": model_main.value,
            "OUROBOROS_MODEL_CODE": model_code.value,
            "OUROBOROS_MODEL_LIGHT": model_light.value,
            "OUROBOROS_MAX_WORKERS": int(workers_slider.value),
            "TOTAL_BUDGET": float(budget_field.value),
            "OUROBOROS_SOFT_TIMEOUT_SEC": int(soft_timeout_slider.value),
            "OUROBOROS_HARD_TIMEOUT_SEC": int(hard_timeout_slider.value),
        })
        save_settings(settings)
        page.open(ft.SnackBar(ft.Text("Settings saved. Restart the app for them to take effect."), duration=3000))
        page.update()

    settings_page = ft.Column(
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Container(
                bgcolor=ft.Colors.with_opacity(0.03, ft.Colors.WHITE),
                padding=ft.padding.symmetric(horizontal=20, vertical=12),
                content=ft.Row([ft.Icon(ft.Icons.SETTINGS_OUTLINED, color=ft.Colors.TEAL_200), ft.Text("Settings", size=16, weight=ft.FontWeight.BOLD)]),
            ),
            ft.Container(
                padding=20,
                content=ft.Column(
                    spacing=24,
                    controls=[
                        ft.Text("API Keys", size=18, weight=ft.FontWeight.BOLD),
                        api_key_field, openai_key_field, anthropic_key_field,
                        ft.Divider(height=1, color=ft.Colors.WHITE10),
                        ft.Text("Models", size=18, weight=ft.FontWeight.BOLD),
                        ft.Row([model_main, model_code, model_light], wrap=True, spacing=16),
                        ft.Divider(height=1, color=ft.Colors.WHITE10),
                        ft.Text("Runtime", size=18, weight=ft.FontWeight.BOLD),
                        ft.Row([
                            ft.Column([ft.Text("Max Workers", size=13, color=ft.Colors.WHITE54), workers_slider]),
                            ft.Column([ft.Text("Soft Timeout", size=13, color=ft.Colors.WHITE54), soft_timeout_slider]),
                            ft.Column([ft.Text("Hard Timeout", size=13, color=ft.Colors.WHITE54), hard_timeout_slider]),
                        ], wrap=True, spacing=24),
                        budget_field,
                        ft.Divider(height=1, color=ft.Colors.WHITE10),
                        ft.FilledButton("Save", icon=ft.Icons.SAVE, on_click=on_save),
                    ],
                ),
            ),
        ],
    )

    pages = [chat_page, dashboard_page, settings_page]
    content_area = ft.Container(expand=True, content=chat_page)

    def on_nav_change(e):
        idx = e.control.selected_index
        content_area.content = pages[idx]
        page.update()

    nav_rail = ft.NavigationRail(
        selected_index=0, label_type=ft.NavigationRailLabelType.ALL, min_width=80, group_alignment=-0.9, on_change=on_nav_change,
        leading=ft.Container(padding=ft.padding.only(top=10, bottom=6), content=ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2, controls=[ft.Text("O", size=28, weight=ft.FontWeight.BOLD, color=ft.Colors.TEAL_200), ft.Text(f"v{APP_VERSION}", size=9, color=ft.Colors.WHITE38)])),
        destinations=[
            ft.NavigationRailDestination(icon=ft.Icons.CHAT_OUTLINED, selected_icon=ft.Icons.CHAT, label="Chat"),
            ft.NavigationRailDestination(icon=ft.Icons.DASHBOARD_OUTLINED, selected_icon=ft.Icons.DASHBOARD, label="Dashboard"),
            ft.NavigationRailDestination(icon=ft.Icons.SETTINGS_OUTLINED, selected_icon=ft.Icons.SETTINGS, label="Settings"),
        ],
    )

    page.add(ft.Row(expand=True, spacing=0, controls=[nav_rail, ft.VerticalDivider(width=1, color=ft.Colors.WHITE10), content_area]))

    # BACKGROUND TASKS
    async def process_chat_inbox():
        while True:
            if CHAT_BRIDGE:
                msg = CHAT_BRIDGE.ui_receive(timeout=0.1)
                if msg:
                    if msg["type"] == "text":
                        chat_list.controls.append(ChatBubble(msg["content"], is_user=False, markdown=msg["markdown"]))
                    elif msg["type"] == "action":
                        pass # Could show a typing indicator
                    try:
                        page.update()
                    except Exception:
                        pass
            await asyncio.sleep(0.1)

    async def update_dashboard():
        while True:
            elapsed = int(time.time() - APP_START)
            h, rem = divmod(elapsed, 3600)
            m, s = divmod(rem, 60)
            uptime_text.value = f"{h}h {m}m {s}s" if h else f"{m}m {s}s" if m else f"{s}s"

            try:
                from supervisor.state import load_state
                st = load_state()
                from supervisor.workers import WORKERS, PENDING, RUNNING
                workers_alive = sum(1 for w in WORKERS.values() if w.proc.is_alive())
                workers_total = len(WORKERS)
                workers_text.value = f"{workers_alive} / {workers_total} active"
                workers_bar.value = (workers_alive / workers_total) if workers_total else 0

                spent = float(st.get("spent_usd") or 0.0)
                limit = float(settings.get("TOTAL_BUDGET", 10.0))
                budget_text.value = f"${spent:.2f} / ${limit:.2f}"
                budget_bar.value = min(1.0, (spent / limit)) if limit else 0
                
                branch_text.value = st.get("current_branch", "ouroboros")
                
                evo_switch.value = bool(st.get("evolution_mode_enabled"))
                
                # Fetch recent log lines
                sup_log = DATA_DIR / "logs" / "supervisor.jsonl"
                if sup_log.exists():
                    lines = sup_log.read_text(encoding="utf-8").strip().splitlines()
                    log_list.controls.clear()
                    for line in lines[-20:]:
                        try:
                            evt = json.loads(line)
                            ts = evt.get("ts", "")[11:19]
                            typ = evt.get("type", "event")
                            log_list.controls.append(ft.Text(f"{ts}  [{typ}] {str(evt)[:100]}", size=11, color=ft.Colors.WHITE38, font_family="monospace"))
                        except Exception:
                            pass
            except Exception:
                pass
                
            try:
                page.update()
            except Exception:
                break
            await asyncio.sleep(2)

    page.run_task(process_chat_inbox)
    page.run_task(update_dashboard)


if __name__ == "__main__":
    bootstrap_repo()
    
    settings = load_settings()
    
    if settings.get("OPENROUTER_API_KEY"):
        # Run supervisor in background thread
        log.info("Starting Supervisor thread...")
        t = threading.Thread(target=run_supervisor, args=(settings,), daemon=True)
        t.start()
        SUPERVISOR_THREAD = t
    else:
        log.warning("OPENROUTER_API_KEY not set. Supervisor will not start until configured.")
        
    log.info("Starting Flet UI...")
    ft.app(target=main)
