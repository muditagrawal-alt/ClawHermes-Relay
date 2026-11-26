#!/usr/bin/env python3
"""Health check for Arize Phoenix, OpenClaw, Hermes Agent, and Slack tokens."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv


def check_slack_token(label: str, token: str) -> str | None:
    if not token or "replace-me" in token:
        print(f"[SKIP] {label}: token not set in .env")
        return None
    resp = httpx.post(
        "https://slack.com/api/auth.test",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )
    data = resp.json()
    if data.get("ok"):
        uid = data.get("user_id", "")
        bot_id = data.get("bot_id", "")
        team = data.get("team", "")
        print(f"[OK]   {label}: team={team!r} user_id={uid} bot_id={bot_id}")
        return uid
    print(f"[FAIL] {label}: {data.get('error', resp.text)}")
    return None


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")

    print("=== Binary & Environment Checks ===")
    for cmd in ("node", "openclaw", "hermes"):
        path = shutil.which(cmd)
        print(f"[{'OK' if path else 'FAIL'}] {cmd}: {path or 'not found'}")

    node_ver = subprocess.check_output(["node", "-v"], text=True).strip()
    print(f"       node version: {node_ver}")

    phoenix_port = os.getenv("PHOENIX_PORT", "6006")
    try:
        r = httpx.get(f"http://localhost:{phoenix_port}", timeout=3.0)
        print(f"[OK]   Arize Phoenix UI reachable at http://localhost:{phoenix_port} (HTTP {r.status_code})")
    except Exception as exc:
        print(f"[WARN] Arize Phoenix not reachable on :{phoenix_port} ({exc})")

    print("\n=== Slack Bot Auth Checks ===")
    oc_uid = check_slack_token("OpenClaw Slack Bot", os.getenv("OPENCLAW_SLACK_BOT_TOKEN", ""))
    hm_uid = check_slack_token("Hermes Slack Bot", os.getenv("HERMES_SLACK_BOT_TOKEN", ""))
    if oc_uid and hm_uid:
        print(f"\nPeer Mention IDs -> OpenClaw: <@{oc_uid}> | Hermes: <@{hm_uid}>")

    return 0


if __name__ == "__main__":
    sys.exit(main())
