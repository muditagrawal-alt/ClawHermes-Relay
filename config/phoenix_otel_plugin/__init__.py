"""phoenix_otel — Hermes Agent OpenInference OTLP plugin for Arize Phoenix.

Captures Hermes turns, Slack handoffs, LLM API generations, and tool executions
as nested OpenInference spans exported to Arize Phoenix over OTLP/HTTP.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    from opentelemetry import context as otel_context
    from opentelemetry import trace as otel_trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.trace import Status, StatusCode, set_span_in_context

    OTEL_AVAILABLE = True
except Exception:  # pragma: no cover - fail-open when OTel deps are missing
    OTEL_AVAILABLE = False

_HANDOFF_RE = re.compile(r"\[handoff:([A-Za-z0-9_.:-]+)\]")
_MAX_FIELD_CHARS = 8000
_MAX_TURNS = 256

_STATE_LOCK = threading.Lock()
_TRACER = None
_PROVIDER = None
_INIT_FAILED = False
_TURNS: Dict[str, "TurnTraceState"] = {}
_PENDING_SLACK_META: Dict[str, Dict[str, str]] = {}


@dataclass
class TurnTraceState:
    key: str
    root_span: Any
    root_ctx: Any
    generations: Dict[str, Any] = field(default_factory=dict)
    tools: Dict[str, Any] = field(default_factory=dict)
    pending_tools_by_name: Dict[str, list] = field(default_factory=dict)
    handoff_id: str = ""
    last_updated_at: float = field(default_factory=time.time)


def _debug_enabled() -> bool:
    return os.getenv("HERMES_PHOENIX_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}


def _truncate(value: Any, limit: int = _MAX_FIELD_CHARS) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [truncated {len(text) - limit} chars]"


def _trace_endpoint() -> str:
    base = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:6006").strip().rstrip("/")
    if not base:
        base = "http://127.0.0.1:6006"
    if base.endswith("/v1/traces"):
        return base
    return f"{base}/v1/traces"


def _project_name() -> str:
    return os.getenv("PHOENIX_PROJECT_NAME", "claw-hermes-relay").strip() or "claw-hermes-relay"


def _get_tracer():
    global _TRACER, _PROVIDER, _INIT_FAILED
    if _INIT_FAILED or not OTEL_AVAILABLE:
        return None
    if _TRACER is not None:
        return _TRACER
    with _STATE_LOCK:
        if _TRACER is not None:
            return _TRACER
        if _INIT_FAILED or not OTEL_AVAILABLE:
            return None
        try:
            project = _project_name()
            endpoint = _trace_endpoint()
            resource = Resource.create(
                {
                    "service.name": "hermes-researcher",
                    "openinference.project.name": project,
                    "agent.framework": "hermes-agent",
                    "agent.role": "seo-aeo-researcher",
                }
            )
            provider = TracerProvider(resource=resource)
            exporter = OTLPSpanExporter(endpoint=endpoint, timeout=5)
            processor = BatchSpanProcessor(
                exporter,
                schedule_delay_millis=1000,
                export_timeout_millis=5000,
            )
            provider.add_span_processor(processor)
            _PROVIDER = provider
            _TRACER = provider.get_tracer("hermes.phoenix_otel", "1.0.0")
            if _debug_enabled():
                logger.info("phoenix_otel initialized: endpoint=%s project=%s", endpoint, project)
            return _TRACER
        except Exception as exc:
            _INIT_FAILED = True
            logger.warning("phoenix_otel init failed (fail-open): %s", exc)
            return None


def _turn_key(*, turn_id: str = "", task_id: str = "", session_id: str = "") -> str:
    if turn_id:
        return f"turn:{turn_id}"
    if task_id and session_id:
        return f"task:{session_id}:{task_id}"
    return f"session:{session_id or task_id or 'default'}"


def _evict_stale_locked() -> None:
    if len(_TURNS) < _MAX_TURNS:
        return
    ordered = sorted(_TURNS.items(), key=lambda item: item[1].last_updated_at)
    for k, st in ordered[: len(_TURNS) - _MAX_TURNS // 2]:
        try:
            st.root_span.end()
        except Exception:
            pass
        _TURNS.pop(k, None)


def _extract_handoff_id(text: str) -> str:
    if not text:
        return ""
    match = _HANDOFF_RE.search(text)
    return match.group(1) if match else ""


def _ensure_turn_state(
    tracer: Any,
    key: str,
    *,
    session_id: str = "",
    platform: str = "",
    model: str = "",
    user_message: Any = None,
) -> TurnTraceState:
    state = _TURNS.get(key)
    if state is not None:
        state.last_updated_at = time.time()
        return state

    _evict_stale_locked()
    user_text = _truncate(user_message)
    handoff_id = _extract_handoff_id(user_text)
    slack_meta = _PENDING_SLACK_META.get(session_id) or _PENDING_SLACK_META.get("latest") or {}
    if not handoff_id:
        handoff_id = slack_meta.get("handoff_id", "")

    span_name = f"hermes.handoff:{handoff_id}" if handoff_id else "hermes.agent.turn"
    attrs: Dict[str, Any] = {
        "openinference.span.kind": "AGENT",
        "agent.name": "hermes-agent",
        "agent.role": "seo-aeo-researcher",
        "session.id": session_id or key,
        "hermes.platform": platform or "cli",
        "llm.model_name": model or "",
    }
    if user_text:
        attrs["input.value"] = user_text
        attrs["input.mime_type"] = "text/plain"
    if handoff_id:
        attrs["handoff.id"] = handoff_id
        attrs["handoff.source"] = "openclaw"
        attrs["handoff.target"] = "hermes"
    for meta_k, meta_v in slack_meta.items():
        if meta_v and meta_k != "handoff_id":
            attrs[f"slack.{meta_k}"] = meta_v

    root_span = tracer.start_span(span_name, attributes=attrs)
    root_ctx = set_span_in_context(root_span)

    if handoff_id:
        chain_span = tracer.start_span(
            "handoff.receive",
            context=root_ctx,
            attributes={
                "openinference.span.kind": "CHAIN",
                "handoff.id": handoff_id,
                "handoff.source": "openclaw",
                "handoff.target": "hermes",
                "input.value": user_text,
            },
        )
        chain_span.end()

    state = TurnTraceState(
        key=key,
        root_span=root_span,
        root_ctx=root_ctx,
        handoff_id=handoff_id,
    )
    _TURNS[key] = state
    return state


def on_pre_gateway_dispatch(*, event: Any = None, **_: Any) -> None:
    if event is None:
        return
    try:
        source = getattr(event, "source", None)
        platform = getattr(getattr(source, "platform", None), "value", "") or ""
        chat_id = str(getattr(source, "chat_id", "") or "")
        thread_ts = str(getattr(source, "thread_ts", "") or getattr(event, "message_id", "") or "")
        user_id = str(getattr(source, "user_id", "") or "")
        text = str(getattr(event, "text", "") or "")
        handoff_id = _extract_handoff_id(text)
        meta = {
            "platform": platform,
            "channel_id": chat_id,
            "thread_ts": thread_ts,
            "sender_user_id": user_id,
            "handoff_id": handoff_id,
        }
        with _STATE_LOCK:
            if chat_id:
                _PENDING_SLACK_META[chat_id] = meta
            _PENDING_SLACK_META["latest"] = meta
    except Exception:
        pass
    return None


def on_pre_api_request(
    *,
    task_id: str = "",
    turn_id: str = "",
    session_id: str = "",
    platform: str = "",
    model: str = "",
    provider: str = "",
    base_url: str = "",
    api_mode: str = "",
    api_call_count: int = 0,
    request_messages: Any = None,
    user_message: Any = None,
    **_: Any,
) -> None:
    tracer = _get_tracer()
    if tracer is None:
        return
    key = _turn_key(turn_id=turn_id, task_id=task_id, session_id=session_id)
    req_key = str(api_call_count or 0)
    with _STATE_LOCK:
        state = _ensure_turn_state(
            tracer,
            key,
            session_id=session_id,
            platform=platform,
            model=model,
            user_message=user_message,
        )
        prev = state.generations.pop(req_key, None)
        if prev is not None:
            try:
                prev.end()
            except Exception:
                pass
        llm_attrs: Dict[str, Any] = {
            "openinference.span.kind": "LLM",
            "llm.model_name": model or "",
            "llm.provider": provider or "",
            "gen_ai.request.model": model or "",
            "gen_ai.system": provider or "",
            "hermes.api_mode": api_mode or "",
            "hermes.base_url": base_url or "",
            "hermes.api_call_count": api_call_count,
            "input.value": _truncate(request_messages if request_messages is not None else user_message),
            "input.mime_type": "application/json",
        }
        if state.handoff_id:
            llm_attrs["handoff.id"] = state.handoff_id
        state.generations[req_key] = tracer.start_span(
            f"llm.{model or 'completion'}",
            context=state.root_ctx,
            attributes=llm_attrs,
        )


def on_post_api_request(
    *,
    task_id: str = "",
    turn_id: str = "",
    session_id: str = "",
    model: str = "",
    api_call_count: int = 0,
    api_duration: float = 0.0,
    finish_reason: str = "",
    usage: Any = None,
    assistant_message: Any = None,
    assistant_content_chars: int = 0,
    assistant_tool_call_count: int = 0,
    **_: Any,
) -> None:
    tracer = _get_tracer()
    if tracer is None:
        return
    key = _turn_key(turn_id=turn_id, task_id=task_id, session_id=session_id)
    req_key = str(api_call_count or 0)
    with _STATE_LOCK:
        state = _TURNS.get(key)
        span = state.generations.pop(req_key, None) if state else None
    if span is None:
        return

    try:
        if isinstance(usage, dict) and usage:
            in_tok = int(usage.get("input_tokens") or 0)
            out_tok = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
            span.set_attribute("llm.token_count.prompt", in_tok)
            span.set_attribute("llm.token_count.completion", out_tok)
            span.set_attribute("llm.token_count.total", in_tok + out_tok)
            span.set_attribute("gen_ai.usage.input_tokens", in_tok)
            span.set_attribute("gen_ai.usage.output_tokens", out_tok)
        if finish_reason:
            span.set_attribute("gen_ai.response.finish_reason", finish_reason)
        if api_duration:
            span.set_attribute("llm.duration_s", round(float(api_duration), 4))

        out_payload: Dict[str, Any] = {}
        if assistant_message is not None:
            content = getattr(assistant_message, "content", None)
            tcs = getattr(assistant_message, "tool_calls", None) or []
            if content:
                out_payload["content"] = content
            if tcs:
                out_payload["tool_calls"] = [
                    {
                        "id": getattr(tc, "id", ""),
                        "name": getattr(getattr(tc, "function", None), "name", ""),
                        "arguments": getattr(getattr(tc, "function", None), "arguments", ""),
                    }
                    for tc in tcs
                ]
        else:
            out_payload = {
                "assistant_content_chars": assistant_content_chars,
                "assistant_tool_call_count": assistant_tool_call_count,
            }
        span.set_attribute("output.value", _truncate(out_payload))
        span.set_attribute("output.mime_type", "application/json")
        span.set_status(Status(StatusCode.OK))
    finally:
        span.end()


def on_pre_tool_call(
    *,
    tool_name: str = "",
    args: Any = None,
    task_id: str = "",
    session_id: str = "",
    tool_call_id: str = "",
    turn_id: str = "",
    **_: Any,
) -> None:
    tracer = _get_tracer()
    if tracer is None:
        return
    key = _turn_key(turn_id=turn_id, task_id=task_id, session_id=session_id)
    with _STATE_LOCK:
        state = _ensure_turn_state(tracer, key, session_id=session_id)
        tool_attrs: Dict[str, Any] = {
            "openinference.span.kind": "TOOL",
            "tool.name": tool_name,
            "tool.parameters": _truncate(args),
            "input.value": _truncate(args),
            "input.mime_type": "application/json",
        }
        if tool_call_id:
            tool_attrs["tool.call_id"] = tool_call_id
        if state.handoff_id:
            tool_attrs["handoff.id"] = state.handoff_id
        span = tracer.start_span(
            f"tool.{tool_name}",
            context=state.root_ctx,
            attributes=tool_attrs,
        )
        if tool_call_id:
            state.tools[tool_call_id] = span
        else:
            state.pending_tools_by_name.setdefault(tool_name, []).append(span)


def on_post_tool_call(
    *,
    tool_name: str = "",
    args: Any = None,
    result: Any = None,
    task_id: str = "",
    session_id: str = "",
    tool_call_id: str = "",
    turn_id: str = "",
    duration_ms: int = 0,
    status: Optional[str] = None,
    error_message: Optional[str] = None,
    **_: Any,
) -> None:
    key = _turn_key(turn_id=turn_id, task_id=task_id, session_id=session_id)
    span = None
    with _STATE_LOCK:
        state = _TURNS.get(key)
        if state is None:
            return
        if tool_call_id:
            span = state.tools.pop(tool_call_id, None)
        if span is None:
            queue = state.pending_tools_by_name.get(tool_name)
            if queue:
                span = queue.pop(0)
                if not queue:
                    state.pending_tools_by_name.pop(tool_name, None)
    if span is None:
        return

    try:
        span.set_attribute("output.value", _truncate(result))
        span.set_attribute("output.mime_type", "text/plain")
        if duration_ms:
            span.set_attribute("tool.duration_ms", int(duration_ms))
        if status:
            span.set_attribute("tool.status", status)
        if error_message or status in {"error", "blocked"}:
            span.set_status(Status(StatusCode.ERROR, str(error_message or status)))
        else:
            span.set_status(Status(StatusCode.OK))
    finally:
        span.end()


def on_post_llm_call(
    *,
    task_id: str = "",
    turn_id: str = "",
    session_id: str = "",
    assistant_response: Any = None,
    **_: Any,
) -> None:
    key = _turn_key(turn_id=turn_id, task_id=task_id, session_id=session_id)
    with _STATE_LOCK:
        state = _TURNS.get(key)
        if state is None:
            return
        if assistant_response is not None:
            state.root_span.set_attribute("output.value", _truncate(assistant_response))
            state.root_span.set_attribute("output.mime_type", "text/plain")
            reply_handoff = _extract_handoff_id(str(assistant_response))
            if reply_handoff:
                state.root_span.set_attribute("handoff.reply_id", reply_handoff)


def on_session_end(
    *,
    task_id: str = "",
    turn_id: str = "",
    session_id: str = "",
    completed: bool = True,
    interrupted: bool = False,
    **_: Any,
) -> None:
    key = _turn_key(turn_id=turn_id, task_id=task_id, session_id=session_id)
    with _STATE_LOCK:
        state = _TURNS.pop(key, None)
        provider = _PROVIDER
    if state is None:
        return

    try:
        for gen_span in list(state.generations.values()):
            try:
                gen_span.end()
            except Exception:
                pass
        for tool_span in list(state.tools.values()):
            try:
                tool_span.end()
            except Exception:
                pass
        if interrupted or not completed:
            state.root_span.set_status(Status(StatusCode.ERROR, "interrupted" if interrupted else "incomplete"))
        else:
            state.root_span.set_status(Status(StatusCode.OK))
        state.root_span.end()
    finally:
        if provider is not None:
            try:
                provider.force_flush(timeout_millis=2000)
            except Exception:
                pass


def register(ctx) -> None:
    ctx.register_hook("pre_gateway_dispatch", on_pre_gateway_dispatch)
    ctx.register_hook("pre_api_request", on_pre_api_request)
    ctx.register_hook("post_api_request", on_post_api_request)
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("post_tool_call", on_post_tool_call)
    ctx.register_hook("post_llm_call", on_post_llm_call)
    ctx.register_hook("on_session_end", on_session_end)
