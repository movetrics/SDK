---
title: Ask Claude or ChatGPT
description: Connect an AI assistant to your Movetrics Cloud workspace, read only.
---

Movetrics Cloud has an MCP connector: an AI assistant can list your recordings and results, read raw samples and draft printable reports, and it cannot change anything.

1. In Claude (Settings → Connectors → Add custom connector) or ChatGPT (developer mode connectors), add `https://beta.movetrics.com/api/mcp`.
2. Sign in with your Movetrics account when asked.
3. Ask, for example: "Compare the jump heights of athlete A-7KQ2M4XD over the last month and show the change."

What the assistant sees: athlete codes, not names; results with the method and engine version that computed them. If it computes something itself from raw samples, it is asked to say so and show its value next to the engine's.

**Tested on:** Claude, on 17 Oct 2026, by the Movetrics team.
