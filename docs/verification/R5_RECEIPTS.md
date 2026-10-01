# Round 5 verification receipts (2026-10-01)

These are local repair/check receipts. The independent round 4 review remains
local-only and is not redistributed. No subsequent independent approval, remote CI,
publication, client endorsement or operational validation is asserted.

The 21 round 5 regressions replayed on the reviewed `publication-r4` candidate
`3946f6fe73dd31640532051d1dd6e84d3a9b908a` all fail. The same tests pass after repairs.
See [before](r5-before.txt), [after](r5-after.txt), and the
[local environment/check manifest](../LOCAL_CHECKS_R5.json).

Findings 2-8 cover AM/PM and unresolved clocks, preservation on download failure
and frozen-path refusal, QA units and denominators, inclusive threshold/support
policy, a default retrospective plan wrapper, organizational metadata, and corrected
bibliography with bounded overlap wording. All four headline metric values, intervals
and denominators match round 4. Raw and normalized records remain withheld.

The clean-checkout regeneration receipt uses the documented hash-verified recovery
route with an independently supplied matching private snapshot. Live acquisition
availability and remote CI remain separate checks. Only runtime timings vary.
