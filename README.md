# Claw × Hermes Relay

Multi-agent collaboration in Slack between **[OpenClaw](https://github.com/openclaw/openclaw)** (Orchestrator & Team Lead) and **[Hermes Agent](https://github.com/NousResearch/hermes-agent)** by Nous Research (Deep SEO/AEO Researcher), with end-to-end OpenTelemetry & OpenInference tracing in **[Arize Phoenix](https://github.com/Arize-ai/phoenix)**.

---

## Use Case: SEO / AEO Brand Visibility Research Assistant

A team member asks `@OpenClaw` in a Slack channel to check how a brand shows up across search results and Answer Engine Optimization (AEO) citations for a set of target queries:

1. **Intake & Delegation (`OpenClaw`):** Parses the request, assigns a correlation tag (`[handoff:seo-aeo-<id>]`), and delegates the query batch in-thread to `@Hermes`.
2. **Deep Research (`Hermes Agent`):** Triggered only on explicit `@Hermes` mention (`allow_bots: "mentions"` + `strict_mention: true`), runs live web search (`ddgs` / search API) and page extraction checks across every query, and replies in-thread tagging `@OpenClaw` with structured evidence.
3. **Executive Synthesis (`OpenClaw`):** Summarizes brand visibility coverage, competitor citations, and top action items back to the channel (omitting `@Hermes` to terminate the loop cleanly).

---

## Architecture

```text
Slack Channel (Socket Mode)
  ├── @OpenClaw (Node 26+ / @openclaw/slack + diagnostics-otel)
  │     ├── Receives human prompt -> posts [handoff:...] delegation to @Hermes
  │     └── Receives @Hermes findings -> posts executive summary
  └── @Hermes (Python 3.11 / Hermes Gateway + web-ddgs + phoenix-otel plugin)
        ├── Receives @Hermes mention -> runs search & URL checks
        └── Posts structured findings -> tags @OpenClaw
              │
              ▼ (OTLP/HTTP -> http://localhost:6006/v1/traces)
       Arize Phoenix (:6006 UI & OTLP Collector)
```

---

## Quick Start

1. **Install dependencies & Hermes plugin:**
   ```bash
   ./scripts/setup_env.sh
   ```
2. **Create two Slack Apps (Socket Mode):**
   - Import `manifests/openclaw-slack-manifest.json` and `manifests/hermes-slack-manifest.json` at `https://api.slack.com/apps`.
   - Install both apps to your Slack workspace, generate an App-Level Token (`xapp-...`, `connections:write`) for each, and invite `@OpenClaw` and `@Hermes` to your collaboration channel.
3. **Configure `.env`:**
   ```bash
   cp .env.example .env
   # Add Slack bot/app tokens, SLACK_COLLAB_CHANNEL_ID, and your LLM key (or use local Ollama)
   ```
4. **Verify & launch:**
   ```bash
   .venv/bin/python scripts/verify_e2e.py
   ./scripts/start_stack.sh
   ```
5. **Inspect traces:** Open `http://localhost:6006` in your browser and select project `claw-hermes-relay`.

---

## Evidence (Screenshots)

> _Screenshots of the live Slack multi-agent conversation and Arize Phoenix trace waterfalls will be added in `docs/screenshots/` after the live end-to-end run._
