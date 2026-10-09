# 4. Keep IMDb's data on the user's machine

Accepted, 2026-10-09.

**Context.** IMDb's datasets are licensed for personal, non-commercial use, with a credit
line. A website or shared database would republish them.

**Decision.** Everything downloaded or derived from IMDb lives in `data/` on the user's
machine. Answers are printed in the terminal or written as a local chart page, each ending
with IMDb's credit. Nothing is uploaded anywhere.

**Consequences.** No website, accounts or sharing: each user syncs their own copy. Charts
work offline, so the chart libraries are vendored rather than loaded from a CDN.
