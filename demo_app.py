"""
Ouroboros Desktop Demo — UI simulator with echo-bot chat.

No real agent code runs. Safe to launch on any machine.

    pip install flet
    python demo_app.py
"""

import asyncio
import random
import time
from datetime import datetime, timezone

import flet as ft

APP_VERSION = "6.2.0"
SESSION_ID = f"{random.randint(0x1000_0000, 0xFFFF_FFFF):08x}"
APP_START = time.time()

MODELS = [
    "anthropic/claude-sonnet-4.6",
    "anthropic/claude-opus-4",
    "google/gemini-3-pro-preview",
    "google/gemini-2.5-flash",
    "openai/gpt-5",
    "openai/o3-mini",
    "meta-llama/llama-4-70b",
]

FAKE_LOG_LINES = [
    "[supervisor] heartbeat: workers=3/5, pending=0, running=1",
    "[agent] tool_call: git_status -> clean",
    "[consciousness] background thought cycle #42 complete",
    "[agent] LLM response: 847 tokens, cost=$0.0032",
    "[supervisor] task t-0a3f completed in 12.4s",
    "[agent] tool_call: read_file -> ouroboros/loop.py (284 lines)",
    "[git] commit: 'refactor: simplify context window packing'",
    "[telegram] message sent to owner (238 chars)",
    "[agent] tool_call: web_search -> 'python asyncio best practices'",
    "[supervisor] evolution check: score=7.2/10, threshold=6.0 — skip",
    "[consciousness] insight: consider adding retry logic to LLM calls",
    "[agent] tool_call: shell_exec -> pytest tests/ -q (14 passed)",
    "[supervisor] budget update: $2.47 / $10.00 (24.7%)",
    "[git] push origin ouroboros -> ok (1 commit)",
    "[agent] review requested: code_quality=8.1, test_coverage=74%",
]


# ---------------------------------------------------------------------------
# Chat bubble widget
# ---------------------------------------------------------------------------

class ChatBubble(ft.Container):
    def __init__(self, text: str, is_user: bool):
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

        self.content = ft.Column(
            spacing=4,
            controls=[
                ft.Text(label, size=11, weight=ft.FontWeight.BOLD, color=label_color),
                ft.Text(text, size=14, selectable=True,
                        color=ft.Colors.WHITE if is_user else ft.Colors.WHITE70),
            ],
        )


class ThinkingBubble(ft.Container):
    """Animated '...' indicator while the bot is 'thinking'."""
    def __init__(self):
        super().__init__()
        self.padding = ft.padding.symmetric(horizontal=14, vertical=10)
        self.border_radius = ft.border_radius.all(16)
        self.margin = ft.margin.only(right=120, top=2, bottom=2)
        self.bgcolor = ft.Colors.with_opacity(0.12, ft.Colors.WHITE)
        self._dots = ft.Text("...", size=14, color=ft.Colors.WHITE70,
                             weight=ft.FontWeight.BOLD)
        self.content = ft.Column(
            spacing=4,
            controls=[
                ft.Text("Ouroboros", size=11, weight=ft.FontWeight.BOLD,
                         color=ft.Colors.TEAL_200),
                self._dots,
            ],
        )


# ---------------------------------------------------------------------------
# Status card for dashboard
# ---------------------------------------------------------------------------

def status_card(title: str, value_control: ft.Control, icon: str,
                icon_color: str = ft.Colors.TEAL_200) -> ft.Container:
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
                    ft.Text(title, size=12, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE54),
                ]),
                value_control,
            ],
        ),
    )


# ---------------------------------------------------------------------------
# Echo-bot response logic
# ---------------------------------------------------------------------------

def echo_response(text: str, state: dict) -> str:
    lowered = text.strip().lower()

    if lowered.startswith("/status"):
        w = state.get("workers_active", 3)
        budget = state.get("budget_spent", 2.47)
        budget_limit = state.get("budget_limit", 10.0)
        uptime = int(time.time() - APP_START)
        return (
            f"--- Ouroboros Status ---\n"
            f"Session: {SESSION_ID}\n"
            f"Branch: ouroboros (clean)\n"
            f"Workers: {w}/5 active\n"
            f"Budget: ${budget:.2f} / ${budget_limit:.2f}\n"
            f"Uptime: {uptime}s\n"
            f"Evolution: {'ON' if state.get('evolution') else 'OFF'}\n"
            f"Consciousness: {'running' if state.get('consciousness') else 'stopped'}\n"
            f"-----------------------"
        )

    if lowered.startswith("/evolve"):
        parts = lowered.split()
        on = not (len(parts) > 1 and parts[1] in ("off", "stop", "0"))
        state["evolution"] = on
        return f"Evolution mode: {'ON' if on else 'OFF'}"

    if lowered.startswith("/review"):
        return "Review task queued. Code quality scan will run in the next cycle."

    if lowered.startswith("/bg"):
        parts = lowered.split()
        action = parts[1] if len(parts) > 1 else "status"
        if action in ("start", "on", "1"):
            state["consciousness"] = True
            return "Background consciousness: started"
        elif action in ("stop", "off", "0"):
            state["consciousness"] = False
            return "Background consciousness: stopped"
        return f"Background consciousness: {'running' if state.get('consciousness') else 'stopped'}"

    if lowered.startswith("/help"):
        return (
            "Available commands:\n"
            "  /status  — show agent status\n"
            "  /evolve [on|off]  — toggle evolution\n"
            "  /review  — queue code review\n"
            "  /bg [start|stop|status]  — consciousness\n"
            "  /help  — this message\n\n"
            "Any other text is echoed back."
        )

    if lowered.startswith("/panic"):
        return "PANIC: All workers stopped. (just kidding, this is a demo)"

    return f"I received your message and processed it through my neural pathways:\n\n\"{text}\"\n\nWhat would you like me to do with this?"


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

def main(page: ft.Page):
    page.title = f"Ouroboros v{APP_VERSION}"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 1100
    page.window.height = 750
    page.padding = 0
    page.spacing = 0

    bot_state = {
        "evolution": True,
        "consciousness": True,
        "pre_push_tests": True,
        "workers_active": 3,
        "budget_spent": 2.47,
        "budget_limit": 10.0,
    }

    # -----------------------------------------------------------------------
    # CHAT PAGE
    # -----------------------------------------------------------------------
    chat_list = ft.ListView(auto_scroll=True, spacing=4, padding=20, expand=True)
    chat_input = ft.TextField(
        hint_text="Message Ouroboros...",
        border_radius=24,
        filled=True,
        expand=True,
        on_submit=lambda e: send_message(e),
        shift_enter=True,
    )

    async def send_message(_e):
        text = chat_input.value
        if not text or not text.strip():
            return
        chat_input.value = ""
        chat_list.controls.append(ChatBubble(text, is_user=True))
        thinking = ThinkingBubble()
        chat_list.controls.append(thinking)
        page.update()

        await asyncio.sleep(random.uniform(0.8, 1.8))

        chat_list.controls.remove(thinking)
        response = echo_response(text, bot_state)
        chat_list.controls.append(ChatBubble(response, is_user=False))
        page.update()

    send_btn = ft.IconButton(
        icon=ft.Icons.SEND_ROUNDED,
        icon_color=ft.Colors.BLUE_400,
        tooltip="Send",
        on_click=send_message,
    )

    # Welcome message
    chat_list.controls.append(
        ChatBubble(
            f"Ouroboros v{APP_VERSION} online. Session {SESSION_ID}.\n"
            "Type /help for available commands, or just chat with me.",
            is_user=False,
        )
    )

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
                content=ft.Row(
                    controls=[chat_input, send_btn],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ),
        ],
    )

    # -----------------------------------------------------------------------
    # DASHBOARD PAGE
    # -----------------------------------------------------------------------
    uptime_text = ft.Text("0s", size=22, weight=ft.FontWeight.BOLD)
    workers_text = ft.Text("3 / 5 active", size=16, weight=ft.FontWeight.BOLD)
    workers_bar = ft.ProgressBar(value=0.6, color=ft.Colors.TEAL_400, width=200)
    budget_text = ft.Text("$2.47 / $10.00", size=16, weight=ft.FontWeight.BOLD)
    budget_bar = ft.ProgressBar(value=0.247, color=ft.Colors.AMBER_400, width=200)
    branch_text = ft.Text("ouroboros", size=16, weight=ft.FontWeight.BOLD,
                          color=ft.Colors.GREEN_300)
    log_list = ft.ListView(auto_scroll=True, spacing=2, height=140, padding=10)

    evo_switch = ft.Switch(label="Evolution Mode", value=True)
    bg_switch = ft.Switch(label="Background Consciousness", value=True)
    test_switch = ft.Switch(label="Pre-push Tests", value=True)
    consciousness_dot = ft.Container(
        width=10, height=10, border_radius=5,
        bgcolor=ft.Colors.TEAL_400,
        animate=ft.Animation(1000, ft.AnimationCurve.EASE_IN_OUT),
    )

    def on_evo_change(e):
        bot_state["evolution"] = evo_switch.value
        page.update()

    def on_bg_change(e):
        bot_state["consciousness"] = bg_switch.value
        consciousness_dot.bgcolor = ft.Colors.TEAL_400 if bg_switch.value else ft.Colors.RED_400
        page.update()

    def on_test_change(e):
        bot_state["pre_push_tests"] = test_switch.value
        page.update()

    evo_switch.on_change = on_evo_change
    bg_switch.on_change = on_bg_change
    test_switch.on_change = on_test_change

    def on_review_click(_e):
        page.open(ft.SnackBar(ft.Text("Review task queued"), duration=2000))
        page.update()

    async def on_restart_click(_e):
        page.open(ft.SnackBar(ft.Text("Restarting agent..."), duration=2000))
        page.update()
        await asyncio.sleep(2)
        page.open(ft.SnackBar(ft.Text("Agent restarted successfully"), duration=2000))
        page.update()

    def on_panic_click(_e):
        def close_dialog(_e2):
            dialog.open = False
            page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("PANIC STOP"),
            content=ft.Text("All workers would be killed. (This is a demo, nothing happened.)"),
            actions=[ft.TextButton("OK", on_click=close_dialog)],
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
                    ft.Text(f"Session {SESSION_ID}", size=11,
                            color=ft.Colors.WHITE38),
                ]),
            ),
            ft.Container(
                padding=20,
                content=ft.Column(
                    spacing=20,
                    controls=[
                        ft.Text(f"Ouroboros v{APP_VERSION}", size=24,
                                weight=ft.FontWeight.BOLD),

                        # Status cards row
                        ft.ResponsiveRow([
                            ft.Container(
                                col={"sm": 6, "md": 3},
                                content=status_card(
                                    "UPTIME", uptime_text,
                                    ft.Icons.TIMER_OUTLINED,
                                ),
                            ),
                            ft.Container(
                                col={"sm": 6, "md": 3},
                                content=status_card(
                                    "WORKERS",
                                    ft.Column([workers_text, workers_bar], spacing=6),
                                    ft.Icons.MEMORY,
                                ),
                            ),
                            ft.Container(
                                col={"sm": 6, "md": 3},
                                content=status_card(
                                    "BUDGET",
                                    ft.Column([budget_text, budget_bar], spacing=6),
                                    ft.Icons.ATTACH_MONEY,
                                    icon_color=ft.Colors.AMBER_400,
                                ),
                            ),
                            ft.Container(
                                col={"sm": 6, "md": 3},
                                content=status_card(
                                    "BRANCH",
                                    ft.Row([
                                        ft.Container(width=8, height=8, border_radius=4,
                                                     bgcolor=ft.Colors.GREEN_400),
                                        branch_text,
                                    ], spacing=8),
                                    ft.Icons.ACCOUNT_TREE_OUTLINED,
                                    icon_color=ft.Colors.GREEN_300,
                                ),
                            ),
                        ]),

                        ft.Divider(height=1, color=ft.Colors.WHITE10),

                        # Toggles
                        ft.Text("Controls", size=14, weight=ft.FontWeight.BOLD,
                                color=ft.Colors.WHITE54),
                        ft.Row([
                            evo_switch,
                            ft.Container(width=20),
                            bg_switch,
                            consciousness_dot,
                            ft.Container(width=20),
                            test_switch,
                        ], wrap=True),

                        # Action buttons
                        ft.Row([
                            ft.ElevatedButton(
                                "Force Review",
                                icon=ft.Icons.RATE_REVIEW_OUTLINED,
                                on_click=on_review_click,
                            ),
                            ft.ElevatedButton(
                                "Restart Agent",
                                icon=ft.Icons.REFRESH,
                                on_click=on_restart_click,
                            ),
                            ft.ElevatedButton(
                                "Panic Stop",
                                icon=ft.Icons.DANGEROUS_OUTLINED,
                                color=ft.Colors.RED_300,
                                on_click=on_panic_click,
                            ),
                        ], wrap=True),

                        ft.Divider(height=1, color=ft.Colors.WHITE10),

                        # Log ticker
                        ft.Text("Live Log", size=14, weight=ft.FontWeight.BOLD,
                                color=ft.Colors.WHITE54),
                        ft.Container(
                            bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.WHITE),
                            border_radius=8,
                            content=log_list,
                        ),
                    ],
                ),
            ),
        ],
    )

    # -----------------------------------------------------------------------
    # SETTINGS PAGE
    # -----------------------------------------------------------------------
    api_key_field = ft.TextField(
        label="OpenRouter API Key",
        value="sk-or-v1-****************************",
        password=True,
        can_reveal_password=True,
        width=500,
    )
    openai_key_field = ft.TextField(
        label="OpenAI API Key (optional)",
        value="",
        password=True,
        can_reveal_password=True,
        width=500,
        hint_text="For web search model",
    )
    anthropic_key_field = ft.TextField(
        label="Anthropic API Key (optional)",
        value="",
        password=True,
        can_reveal_password=True,
        width=500,
        hint_text="For Claude Code CLI",
    )
    model_main = ft.Dropdown(
        label="Main Model",
        width=350,
        value="anthropic/claude-sonnet-4.6",
        options=[ft.dropdown.Option(m) for m in MODELS],
    )
    model_code = ft.Dropdown(
        label="Code Model",
        width=350,
        value="anthropic/claude-sonnet-4.6",
        options=[ft.dropdown.Option(m) for m in MODELS],
    )
    model_light = ft.Dropdown(
        label="Light Model",
        width=350,
        value="google/gemini-3-pro-preview",
        options=[ft.dropdown.Option(m) for m in MODELS],
    )
    workers_slider = ft.Slider(
        min=1, max=10, value=5, divisions=9, label="{value}",
        width=350,
    )
    budget_field = ft.TextField(
        label="Total Budget ($)",
        value="10.00",
        width=200,
        keyboard_type=ft.KeyboardType.NUMBER,
    )
    soft_timeout_slider = ft.Slider(
        min=60, max=3600, value=600, divisions=59, label="{value}s",
        width=350,
    )
    hard_timeout_slider = ft.Slider(
        min=120, max=7200, value=1800, divisions=59, label="{value}s",
        width=350,
    )

    def on_save(_e):
        page.open(ft.SnackBar(ft.Text("Settings saved"), duration=2000))
        page.update()

    def on_reset(_e):
        model_main.value = "anthropic/claude-sonnet-4.6"
        model_code.value = "anthropic/claude-sonnet-4.6"
        model_light.value = "google/gemini-3-pro-preview"
        workers_slider.value = 5
        budget_field.value = "10.00"
        soft_timeout_slider.value = 600
        hard_timeout_slider.value = 1800
        page.open(ft.SnackBar(ft.Text("Settings reset to defaults"), duration=2000))
        page.update()

    settings_page = ft.Column(
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Container(
                bgcolor=ft.Colors.with_opacity(0.03, ft.Colors.WHITE),
                padding=ft.padding.symmetric(horizontal=20, vertical=12),
                content=ft.Row([
                    ft.Icon(ft.Icons.SETTINGS_OUTLINED, color=ft.Colors.TEAL_200),
                    ft.Text("Settings", size=16, weight=ft.FontWeight.BOLD),
                ]),
            ),
            ft.Container(
                padding=20,
                content=ft.Column(
                    spacing=24,
                    controls=[
                        ft.Text("API Keys", size=18, weight=ft.FontWeight.BOLD),
                        api_key_field,
                        openai_key_field,
                        anthropic_key_field,

                        ft.Divider(height=1, color=ft.Colors.WHITE10),
                        ft.Text("Models", size=18, weight=ft.FontWeight.BOLD),
                        ft.Row([model_main, model_code, model_light], wrap=True,
                               spacing=16),

                        ft.Divider(height=1, color=ft.Colors.WHITE10),
                        ft.Text("Runtime", size=18, weight=ft.FontWeight.BOLD),

                        ft.Row([
                            ft.Column([
                                ft.Text("Max Workers", size=13, color=ft.Colors.WHITE54),
                                workers_slider,
                            ]),
                            ft.Column([
                                ft.Text("Soft Timeout", size=13, color=ft.Colors.WHITE54),
                                soft_timeout_slider,
                            ]),
                            ft.Column([
                                ft.Text("Hard Timeout", size=13, color=ft.Colors.WHITE54),
                                hard_timeout_slider,
                            ]),
                        ], wrap=True, spacing=24),

                        budget_field,

                        ft.Divider(height=1, color=ft.Colors.WHITE10),
                        ft.Row([
                            ft.FilledButton("Save", icon=ft.Icons.SAVE,
                                            on_click=on_save),
                            ft.OutlinedButton("Reset to Defaults",
                                              icon=ft.Icons.RESTORE,
                                              on_click=on_reset),
                        ], spacing=12),
                    ],
                ),
            ),
        ],
    )

    # -----------------------------------------------------------------------
    # NAVIGATION
    # -----------------------------------------------------------------------
    pages = [chat_page, dashboard_page, settings_page]
    content_area = ft.Container(expand=True, content=chat_page)

    def on_nav_change(e):
        idx = e.control.selected_index
        content_area.content = pages[idx]
        page.update()

    nav_rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=80,
        group_alignment=-0.9,
        on_change=on_nav_change,
        leading=ft.Container(
            padding=ft.padding.only(top=10, bottom=6),
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
                controls=[
                    ft.Text("O", size=28, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.TEAL_200),
                    ft.Text(f"v{APP_VERSION}", size=9, color=ft.Colors.WHITE38),
                ],
            ),
        ),
        destinations=[
            ft.NavigationRailDestination(
                icon=ft.Icons.CHAT_OUTLINED,
                selected_icon=ft.Icons.CHAT,
                label="Chat",
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.DASHBOARD_OUTLINED,
                selected_icon=ft.Icons.DASHBOARD,
                label="Dashboard",
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.SETTINGS_OUTLINED,
                selected_icon=ft.Icons.SETTINGS,
                label="Settings",
            ),
        ],
    )

    page.add(
        ft.Row(
            expand=True,
            spacing=0,
            controls=[
                nav_rail,
                ft.VerticalDivider(width=1, color=ft.Colors.WHITE10),
                content_area,
            ],
        )
    )

    # -----------------------------------------------------------------------
    # BACKGROUND TASKS — uptime counter + fake log ticker
    # -----------------------------------------------------------------------
    async def tick_uptime():
        while True:
            elapsed = int(time.time() - APP_START)
            h, rem = divmod(elapsed, 3600)
            m, s = divmod(rem, 60)
            if h:
                uptime_text.value = f"{h}h {m}m {s}s"
            elif m:
                uptime_text.value = f"{m}m {s}s"
            else:
                uptime_text.value = f"{s}s"
            try:
                page.update()
            except Exception:
                break
            await asyncio.sleep(1)

    async def tick_logs():
        while True:
            await asyncio.sleep(random.uniform(2.0, 5.0))
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            line = random.choice(FAKE_LOG_LINES)
            log_list.controls.append(
                ft.Text(f"{ts}  {line}", size=11, color=ft.Colors.WHITE38,
                        font_family="monospace"),
            )
            if len(log_list.controls) > 200:
                log_list.controls = log_list.controls[-100:]
            try:
                page.update()
            except Exception:
                break

    async def pulse_consciousness():
        while True:
            if bot_state.get("consciousness"):
                consciousness_dot.opacity = 0.3
                try:
                    page.update()
                except Exception:
                    break
                await asyncio.sleep(0.8)
                consciousness_dot.opacity = 1.0
                try:
                    page.update()
                except Exception:
                    break
                await asyncio.sleep(0.8)
            else:
                consciousness_dot.opacity = 1.0
                try:
                    page.update()
                except Exception:
                    break
                await asyncio.sleep(1)

    page.run_task(tick_uptime)
    page.run_task(tick_logs)
    page.run_task(pulse_consciousness)


if __name__ == "__main__":
    ft.app(target=main)
