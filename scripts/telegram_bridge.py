#!/usr/bin/env python3
import asyncio
import json
import os
import threading
import time
from collections import deque

import requests
import websocket

SERVER_HTTP = os.environ.get("OUROBOROS_HTTP", "http://127.0.0.1:8765")
SERVER_WS = os.environ.get("OUROBOROS_WS", "ws://127.0.0.1:8765/ws")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

OUTBOX = deque(maxlen=500)


def tg_api(method: str, payload: dict):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    return requests.post(url, json=payload, timeout=30)


def ws_listener():
    while True:
        try:
            ws = websocket.create_connection(SERVER_WS, timeout=30)
            while True:
                msg = ws.recv()
                if not msg:
                    continue
                try:
                    data = json.loads(msg)
                except Exception:
                    continue
                if data.get("type") == "chat" and data.get("role") == "assistant":
                    text = str(data.get("content") or "").strip()
                    if text:
                        OUTBOX.append((time.time(), text))
        except Exception:
            time.sleep(2)


def post_command(text: str):
    requests.post(f"{SERVER_HTTP}/api/command", json={"cmd": text}, timeout=15)


def _normalize_text(txt: str) -> str:
    t = (txt or "").strip()

    # Strip noisy OpenClaw prefix lines when present.
    if t.startswith("[agents/auth-profiles]"):
        lines = [ln for ln in t.splitlines() if ln.strip()]
        if len(lines) > 1:
            t = "\n".join(lines[1:]).strip()

    # Try parse full text as JSON, or parse from first '{' if prefixed.
    candidates = [t]
    i = t.find("{")
    if i > 0:
        candidates.append(t[i:])

    for c in candidates:
        try:
            j = json.loads(c)
            if isinstance(j, dict) and isinstance(j.get("payloads"), list):
                parts = [str(p.get("text", "")).strip() for p in j.get("payloads", []) if isinstance(p, dict)]
                parts = [p for p in parts if p]
                if parts:
                    return "\n\n".join(parts)
        except Exception:
            continue

    return t


def wait_reply(after_ts: float, timeout_sec: int = 90) -> str:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        for ts, txt in list(OUTBOX):
            if ts >= after_ts:
                return _normalize_text(txt)
        time.sleep(0.5)
    return "⏳ Команда принята, но ответ ещё не пришёл."


def main():
    if not BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")

    t = threading.Thread(target=ws_listener, daemon=True)
    t.start()

    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            resp = requests.get(url, params={"timeout": 30, "offset": offset}, timeout=40)
            data = resp.json()
            for upd in data.get("result", []):
                offset = max(offset, int(upd.get("update_id", 0)) + 1)
                msg = upd.get("message") or {}
                chat = msg.get("chat") or {}
                chat_id = str(chat.get("id", ""))
                text = str(msg.get("text") or "").strip()
                if not text:
                    continue
                if ALLOWED_CHAT and chat_id != ALLOWED_CHAT:
                    continue

                started = time.time()
                try:
                    post_command(text)
                    answer = wait_reply(started, timeout_sec=90)
                except Exception as e:
                    answer = f"❌ Ошибка bridge: {e}"

                tg_api("sendMessage", {"chat_id": chat_id, "text": answer[:4000]})
        except Exception:
            time.sleep(2)


if __name__ == "__main__":
    main()
