---
name: seo-aeo-research
description: >
  Deep SEO and Answer Engine Optimization (AEO) brand visibility research skill
  for Slack collaboration with OpenClaw. Checks live search results and cited
  pages per query, records brand presence, competitor citations, and returns
  structured evidence back to OpenClaw.
---

# SEO / AEO Research Workflow (Hermes Agent)

When `@OpenClaw` (or a team member) mentions you in Slack with a `[handoff:...]` research request:

1. **Preserve Correlation Context:**
   - Keep the exact `[handoff:...]` tag from the incoming prompt in your final reply.
2. **Execute Real Tool Calls:**
   - For each query in the request, run `web_search` (and `web_extract` / `terminal` HTTP check when helpful to verify structured schema, FAQ/AEO readiness, or brand mentions on cited pages).
   - Never guess or invent URLs, rankings, or brand appearances. If a query returns no brand match in the top results, report `Not observed in top results` along with the actual domains that appeared.
3. **Structured Output Back to OpenClaw:**
   - Start your reply with `<@OPENCLAW_BOT_USER_ID> [handoff:<same_id>] Research complete.`
   - Provide a concise per-query breakdown:
     - Query
     - Brand Presence (`Found (rank/context)` or `Missing`)
     - Top Competitors / Cited Domains
     - AEO Signal Note (e.g., comparison listicle, Reddit/community thread, authoritative guide, missing FAQ/schema)
   - **CRITICAL ANTI-LOOP RULE:** Only tag `<@OPENCLAW_BOT_USER_ID>` once when delivering the final research findings. Do not send follow-up chatter.
