#!/usr/bin/env python3
"""Verify Hermes phoenix_otel plugin hooks emit OpenInference spans cleanly."""
from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path


def load_plugin():
    plugin_path = Path.home() / ".hermes" / "plugins" / "phoenix_otel" / "__init__.py"
    spec = importlib.util.spec_from_file_location("phoenix_otel_test", plugin_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["phoenix_otel_test"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    os.environ.setdefault("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:6006")
    os.environ.setdefault("PHOENIX_PROJECT_NAME", "claw-hermes-relay")

    mod = load_plugin()

    registered = {}

    class DummyCtx:
        def register_hook(self, name, fn):
            registered[name] = fn

    mod.register(DummyCtx())
    expected = {
        "pre_gateway_dispatch",
        "pre_api_request",
        "post_api_request",
        "pre_tool_call",
        "post_tool_call",
        "post_llm_call",
        "on_session_end",
    }
    missing = expected - set(registered)
    if missing:
        print(f"Missing hooks: {missing}")
        return 1

    # Simulate Slack gateway message from OpenClaw -> Hermes
    event = types.SimpleNamespace(
        message_id="1700000001.000100",
        text="<@U_HERMES> [handoff:seo-aeo-smoke] Audit 2 queries",
        source=types.SimpleNamespace(
            platform=types.SimpleNamespace(value="slack"),
            chat_id="C_TEST_CHANNEL",
            thread_ts="1700000000.000050",
            user_id="U_OPENCLAW",
        ),
    )
    registered["pre_gateway_dispatch"](event=event)

    turn_id = "turn-smoke-1"
    session_id = "slack:C_TEST_CHANNEL:1700000000.000050"
    registered["pre_api_request"](
        task_id="task-1",
        turn_id=turn_id,
        session_id=session_id,
        platform="slack",
        model="qwen3.5:9b",
        provider="ollama",
        api_call_count=1,
        request_messages=[{"role": "user", "content": event.text}],
        user_message=event.text,
    )
    registered["pre_tool_call"](
        tool_name="web_search",
        args={"query": "best software development companies"},
        task_id="task-1",
        session_id=session_id,
        tool_call_id="tc_1",
        turn_id=turn_id,
    )
    registered["post_tool_call"](
        tool_name="web_search",
        args={"query": "best software development companies"},
        result={"results": [{"title": "Example", "url": "https://example.com"}]},
        task_id="task-1",
        session_id=session_id,
        tool_call_id="tc_1",
        turn_id=turn_id,
        duration_ms=120,
        status="ok",
    )
    assistant_msg = types.SimpleNamespace(content="Research findings compiled.", tool_calls=[])
    registered["post_api_request"](
        task_id="task-1",
        turn_id=turn_id,
        session_id=session_id,
        model="qwen3.5:9b",
        api_call_count=1,
        api_duration=0.45,
        finish_reason="stop",
        usage={"input_tokens": 180, "output_tokens": 42},
        assistant_message=assistant_msg,
    )
    registered["post_llm_call"](
        task_id="task-1",
        turn_id=turn_id,
        session_id=session_id,
        assistant_response="<@U_OPENCLAW> [handoff:seo-aeo-smoke] Research complete.",
    )
    registered["on_session_end"](
        task_id="task-1",
        turn_id=turn_id,
        session_id=session_id,
        completed=True,
        interrupted=False,
    )
    print("Hermes phoenix_otel plugin hook simulation OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
