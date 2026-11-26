#!/usr/bin/env python3
"""Smoke test verifying Arize Phoenix OTLP ingestion and GraphQL trace query."""
from __future__ import annotations

import os
import sys
import time
import uuid

import httpx
from dotenv import load_dotenv
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor


def main() -> int:
    load_dotenv()
    port = os.getenv("PHOENIX_PORT", "6006")
    project = os.getenv("PHOENIX_PROJECT_NAME", "claw-hermes-relay")
    base_url = f"http://127.0.0.1:{port}"

    handoff_id = f"smoke-{uuid.uuid4().hex[:8]}"
    resource = Resource.create(
        {
            "service.name": "hermes-researcher",
            "openinference.project.name": project,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        SimpleSpanProcessor(OTLPSpanExporter(endpoint=f"{base_url}/v1/traces", timeout=5))
    )
    tracer = provider.get_tracer("claw_hermes_relay.smoke", "1.0.0")

    with tracer.start_as_current_span(
        f"hermes.handoff:{handoff_id}",
        attributes={
            "openinference.span.kind": "AGENT",
            "handoff.id": handoff_id,
            "input.value": "Smoke test delegation from OpenClaw to Hermes",
            "output.value": "Smoke test trace recorded cleanly",
        },
    ):
        with tracer.start_as_current_span(
            "tool.web_search",
            attributes={
                "openinference.span.kind": "TOOL",
                "tool.name": "web_search",
                "input.value": '{"query": "smoke test"}',
                "output.value": "ok",
            },
        ):
            time.sleep(0.02)

    provider.force_flush(timeout_millis=5000)
    provider.shutdown()

    # Query Phoenix GraphQL API to verify span landed in project
    query = """
    query {
      projects(first: 20) {
        edges {
          node {
            name
            traceCount
          }
        }
      }
    }
    """
    time.sleep(1.5)
    resp = httpx.post(
        f"{base_url}/graphql",
        json={"query": query},
        timeout=5.0,
    )
    print(f"Phoenix GraphQL HTTP {resp.status_code}: {resp.text[:500]}")
    if resp.status_code != 200:
        return 1
    edges = resp.json().get("data", {}).get("projects", {}).get("edges", [])
    matched = [e["node"] for e in edges if e.get("node", {}).get("name") == project]
    if not matched or matched[0].get("traceCount", 0) < 1:
        print(f"Expected project {project!r} with traceCount >= 1, got: {edges}")
        return 1
    print(f"Verified Phoenix project {project!r} traceCount={matched[0]['traceCount']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
