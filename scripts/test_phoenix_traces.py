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
    base_url = f"http://localhost:{port}"

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
    query($name: String!) {
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
    time.sleep(1.0)
    resp = httpx.post(
        f"{base_url}/graphql",
        json={"query": query, "variables": {"name": project}},
        timeout=5.0,
    )
    print(f"Phoenix GraphQL HTTP {resp.status_code}: {resp.text[:400]}")
    return 0 if resp.status_code == 200 and project in resp.text else 1


if __name__ == "__main__":
    sys.exit(main())
