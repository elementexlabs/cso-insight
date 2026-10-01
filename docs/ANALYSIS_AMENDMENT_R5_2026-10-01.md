# Analysis amendment, round 5 (2026-10-01)

Status: retrospective, after results and the round 4 independent review. The archived
plan and its SHA-256 remain unchanged; chronology is not independently established.

1. Incident clocks now honor explicit AM/PM: 12 AM is midnight and 12 PM is noon.
   Without a marker, valid clocks use 24-hour time. Consistent 13-23 PM and 0 AM
   inputs retain their 24-hour meaning. 0 PM is unresolved because its source
   convention is ambiguous; 13-23 AM conflicts. Missing/malformed clocks or unknown
   markers also remain null, with a per-row reason and an aggregate QA flag. The
   separate incident date is retained. This does not change calendar-year splits,
   co-reported rainfall pairing or plausibility eligibility; no time-zone/weather join
   is asserted. Normalized rows are regenerated privately, not distributed.
2. Retain the threshold implementation: positive **at or above** the eligible
   2022-2024 training rainfall 75th percentile, using at least three observations
   per identifier. Unsupported identifiers retain an infinite threshold and default
   negative; missing test rainfall is excluded. Export support and denominators.
   In this snapshot, 1,635 of 1,643 test report rows have threshold support; eight
   rows across five identifiers default negative. The fraction stays 395/1,643.
   Five rows equal their threshold. This describes reported events only, without
   non-event-day detection or accuracy claims.
3. QA exports distinguish identifier missingness counts (>50% within an identifier)
   from report-row flags, report full-feed denominators and unique quarantine counts,
   and disclose overlapping flags. Neither missingness nor unresolved times changes
   eligibility for the current calendar-year analysis.

All four headline values, intervals, denominators and rankings are unchanged.
See the local verification receipt and regenerated cohort ledger for measured checks.
