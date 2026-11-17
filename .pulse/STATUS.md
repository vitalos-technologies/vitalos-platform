---
pulse: status/1
project: platform
name: Vitalos Platform
repo: vitalos-technologies/vitalos-platform
visibility: public
stage: Live
health: amber
progress: 74
updated: 2026-11-17
updated_by: session_01Cr6fhcy2Ch1rivzTMCj8ek (engineering); seeded from the Pulse record of 14 Nov 2026, next session to verify
---

# Vitalos Platform: status

## Summary
Monorepo behind the live vitalos.co.uk website (Next.js on Vercel), the internal Django Super Admin and the client portal. The AI & Data launch milestone (VAD-001 to VAD-010), the AI-assisted admin workspace and the client portal are built and live; the Relay assistant is built but switched off in production, with the site assistant moved to Askbridge (ADR-045). Remaining work is mostly owner switches and customer-dependent tasks.

## Now

## Next
- Merge open Dependabot PRs once CI is green
- WS-006 remainder: per-milestone tasks and test cases, AI-drafted progress summaries with human approval
- Triage stale PRs #87, #82, #70, #69 with the owner
- PORTAL-14 later phases: email OTP, contractual e-signature, live monitoring, retention jobs
- Customer discovery (VAD-011) toward the first paid engagement

## Needs Temitope
- Tracked privately on Pulse (this repository is public).

## Blockers
- VAD-011 to VAD-019 need customer conversations and a real customer
- Live AI features stay off until the owner switches them on
- Tracked privately on Pulse (this repository is public).

## Links
- Website: https://vitalos.co.uk
- AI & Data: https://vitalos.co.uk/ai-data
- Askbridge: https://askbridge.vitalos.co.uk
