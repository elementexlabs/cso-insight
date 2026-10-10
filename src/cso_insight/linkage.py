"""Conservative local discharge linkage, independent of the existing CSO analysis."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import cast

from cso_insight.attribution import output_attribution
from cso_insight.config import EXPECTED_DOWNLOAD_SHA256
from cso_insight.ingest import parse_incident_clock, parse_incident_date

NOTIFICATION = "Public Notification Report"
VERIFIED = "Verified Data Report"
RULE_VERSION = "linkage/2"
WINDOW_SECONDS = 15 * 60
HIGH_VOLUME_GALLONS = 10_000_000


def normal(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def known(value: str) -> bool:
    return normal(value) not in {"", "unknown", "other", "n/a", "none"}


def timestamp(value: str) -> datetime | None:
    try:
        result = datetime.fromisoformat(value.strip())
        return result if result.tzinfo is None else None
    except ValueError:
        return None


def number(value: str) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except ValueError:
        return None


@dataclass(frozen=True)
class SourceRow:
    """CSV record ordinal and unmodified fields. Ordinals do not mean line numbers."""

    ordinal: int
    raw: dict[str, str]
    day: date | None
    start: datetime | None
    clock_status: str
    snapshot_hash: str = "synthetic"

    @property
    def key(self) -> str:
        return f"{self.snapshot_hash}:row-{self.ordinal:06d}"

    def get(self, field: str) -> str:
        return self.raw.get(field, "").strip()

    @property
    def retracted(self) -> bool:
        # A zero volume, ceased discharge or free-text remark is not a retraction.
        return normal(self.get("reportingType")) in {"retracted", "retraction"}

    @property
    def flags(self) -> list[str]:
        volume = number(self.get("volumnOfEvent"))
        flags: list[str] = []
        if volume is not None and volume > HIGH_VOLUME_GALLONS:
            flags.append("high_volume_review")
        for field in ("volumnOfEvent", "rainfallData", "hours", "minutes"):
            value = self.get(field)
            numeric = number(value)
            if value and (numeric is None or numeric < 0):
                flags.append(f"invalid_{field}_review")
        for field, bound in (("latitude", 90), ("longitude", 180)):
            value = self.get(field)
            numeric = number(value)
            if value and (numeric is None or not -bound <= numeric <= bound):
                flags.append(f"invalid_{field}_review")
        if self.retracted:
            flags.append("explicit_retraction")
        return flags


def load_source_rows(path: Path) -> list[SourceRow]:
    """Retain every source row, every column and every original field value."""
    rows: list[SourceRow] = []
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with path.open(encoding="utf-8", newline="") as handle:
        for ordinal, raw in enumerate(csv.DictReader(handle), 1):
            if None in raw or any(value is None for value in raw.values()):
                raise ValueError(f"Malformed CSV record {ordinal}")
            day = None
            with suppress(ValueError, IndexError):
                day = parse_incident_date(raw.get("incidentDate", ""))
            clock, status = parse_incident_clock(raw.get("incidentTime", ""), raw.get("amPm", ""))
            start = datetime.combine(day, clock) if day is not None and clock is not None else None
            rows.append(SourceRow(ordinal, raw, day, start, status, digest))
    return rows


def permittee(row: SourceRow) -> str:
    # Name blocking also finds pairs where only one stage has a permit number.
    name = row.get("permiteeName")
    identifier = row.get("permiteeId")
    return normal(name) if known(name) else normal(identifier) if known(identifier) else ""


def stage_known(row: SourceRow) -> bool:
    kind = row.get("reporterClass")
    reporting = normal(row.get("reportingType"))
    return (kind == VERIFIED and reporting in {"", "retracted", "retraction"}) or (
        kind == NOTIFICATION
        and reporting
        in {"initial-ceased", "initial-ongoing", "ongoing", "ceased", "retracted", "retraction"}
    )


def evidence_issue(row: SourceRow) -> str | None:
    """An unmatched row is a negative only when identity evidence is sufficient."""
    if not stage_known(row):
        return "unknown reporting-stage taxonomy"
    if not permittee(row):
        return "permittee identity unresolved"
    if not known(row.get("eventType")):
        return "event type missing"
    if row.start is None or row.day is None:
        return "date or clock unresolved"
    if any(flag in row.flags for flag in ("invalid_latitude_review", "invalid_longitude_review")):
        return "invalid coordinates; human review required"
    if not known(row.get("outfallId")) and not (
        known(row.get("location"))
        and number(row.get("latitude")) is not None
        and number(row.get("longitude")) is not None
    ):
        return "location unresolved"
    if timestamp(row.get("submittedDate")) is None:
        return "submission chronology unresolved"
    return None


def pair_rule(left: SourceRow, right: SourceRow, *, tolerance_minutes: int = 15) -> tuple[str, str]:
    """A source identifier cannot override contradictory location or timing evidence."""
    if (
        isinstance(tolerance_minutes, bool)
        or not isinstance(cast(object, tolerance_minutes), int)
        or tolerance_minutes <= 0
    ):
        raise ValueError("Start-time tolerance must be a positive integer in minutes")
    if {left.get("reporterClass"), right.get("reporterClass")} != {NOTIFICATION, VERIFIED}:
        return "no link", "not a notification and verified pair"
    if not stage_known(left) or not stage_known(right):
        return "abstain", "unknown reporting-stage taxonomy"
    if any(
        flag in row.flags
        for row in (left, right)
        for flag in ("invalid_latitude_review", "invalid_longitude_review")
    ):
        return "abstain", "invalid coordinates; human review required"
    for field in ("permiteeId", "permiteeName", "eventType", "outfallId"):
        a, b = left.get(field), right.get(field)
        if known(a) and known(b) and normal(a) != normal(b):
            return "no link", f"contradictory {field}"
    if left.day is not None and right.day is not None and left.day != right.day:
        return "no link", "different incident dates"
    if (
        left.start is not None
        and right.start is not None
        and abs((left.start - right.start).total_seconds()) > tolerance_minutes * 60
    ):
        return "no link", f"start times outside {tolerance_minutes}-minute window"
    if not permittee(left) or permittee(left) != permittee(right):
        return "abstain", "permittee identity unresolved"
    if not known(left.get("eventType")) or not known(right.get("eventType")):
        return "abstain", "event type missing"
    if left.start is None or right.start is None or left.day is None or right.day is None:
        return "abstain", "date or clock unresolved"
    ids = [left.get("outfallId"), right.get("outfallId")]
    coordinates: list[tuple[float | None, float | None]] = []
    for row in (left, right):
        lat, lon = number(row.get("latitude")), number(row.get("longitude"))
        coordinates.append((lat, lon))
    if all(a is not None and b is not None for a, b in coordinates):
        a_lat, a_lon = coordinates[0]
        b_lat, b_lon = coordinates[1]
        assert a_lat is not None and a_lon is not None and b_lat is not None and b_lon is not None
        if abs(a_lat - b_lat) > 0.0001 or abs(a_lon - b_lon) > 0.0001:
            return "no link", "contradictory coordinates"
    location = all(known(value) for value in ids) and normal(ids[0]) == normal(ids[1])
    if not location:
        location = (
            known(left.get("location"))
            and normal(left.get("location")) == normal(right.get("location"))
            and all(a is not None and b is not None for a, b in coordinates)
        )
    if not location:
        return "abstain", "location unresolved"
    notification, verified = (
        (left, right) if left.get("reporterClass") == NOTIFICATION else (right, left)
    )
    first, later = (
        timestamp(notification.get("submittedDate")),
        timestamp(verified.get("submittedDate")),
    )
    if first is None or later is None or later <= first:
        return "abstain", "later verified submission not established"
    parent = verified.get("parentIncidentId") == notification.get("incidentId")
    parent = parent and bool(notification.get("incidentId"))
    same_number = known(left.get("incidentNumber")) and left.get("incidentNumber") == right.get(
        "incidentNumber"
    )
    return "link", (
        "explicit parent with compatible location and time"
        if parent
        else "same incident number with compatible location and time"
        if same_number
        else f"unique compatible location and {tolerance_minutes}-minute start window"
    )


def field_provenance(rows: list[SourceRow]) -> dict[str, object]:
    """Keep all values; only identical later-stage values supersede an earlier value."""
    result: dict[str, object] = {}
    for field in sorted({field for row in rows for field in row.raw}):
        # Stage/identifier metadata differ by design, not as discharge measurements.
        identity = field in {
            "",
            "incidentId",
            "incidentNumber",
            "parentIncidentId",
            "reporterClass",
            "reportingType",
            "submittedDate",
        }
        present = [row for row in rows if row.get(field) and not row.retracted]
        conflicting = not identity and len({row.get(field) for row in present}) > 1
        later = [row for row in present if row.get("reporterClass") == VERIFIED]
        entries = []
        for row in rows:
            status = "current"
            if not row.get(field):
                status = "missing"
            elif row.retracted:
                status = "retracted"
            elif conflicting:
                status = "conflicting"
            elif not identity and row.get("reporterClass") == NOTIFICATION and later:
                a, b = timestamp(row.get("submittedDate")), timestamp(later[0].get("submittedDate"))
                if a is not None and b is not None and b > a:
                    status = "superseded"
            entries.append(
                {"source_row": row.key, "value": row.raw.get(field, ""), "status": status}
            )
        result[field] = {
            "state": "conflicting"
            if conflicting
            else "observed"
            if present
            else "retracted"
            if any(row.retracted for row in rows)
            else "missing",
            "values": entries,
        }
    return result


@dataclass
class LinkageResult:
    rows: list[SourceRow]
    groups: list[dict[str, object]]
    events: list[dict[str, object]]
    summary: dict[str, object]


def build_linkage(
    rows: list[SourceRow], digest: str, *, tolerance_minutes: int = 15
) -> LinkageResult:
    """Partition source rows using unique reciprocal cross-stage pairs only."""
    if (
        isinstance(tolerance_minutes, bool)
        or not isinstance(cast(object, tolerance_minutes), int)
        or tolerance_minutes <= 0
    ):
        raise ValueError("Start-time tolerance must be a positive integer in minutes")
    blocks: dict[tuple[str, date | None], list[SourceRow]] = defaultdict(list)
    by_id: dict[str, list[SourceRow]] = defaultdict(list)
    for row in rows:
        blocks[(permittee(row), row.day)].append(row)
        if row.get("incidentId"):
            by_id[row.get("incidentId")].append(row)
    candidates: dict[str, list[tuple[SourceRow, str, str]]] = {}
    for row in rows:
        if row.get("reporterClass") != NOTIFICATION:
            continue
        pool = {
            other.key: other
            for other in blocks[(permittee(row), row.day)]
            if other.get("reporterClass") == VERIFIED
        }
        # Explicit identifiers are considered across blocks, then tested for contradictions.
        candidates[row.key] = [
            (other, *pair_rule(row, other, tolerance_minutes=tolerance_minutes))
            for other in sorted(pool.values(), key=lambda r: r.ordinal)
        ]
    # Parent references can be absent in this snapshot; retain an executable route for them.
    for verified in rows:
        if verified.get("reporterClass") != VERIFIED:
            continue
        for notification in by_id.get(verified.get("parentIncidentId"), []):
            if notification.get("reporterClass") == NOTIFICATION:
                group = candidates[notification.key]
                if not any(other.key == verified.key for other, _, _ in group):
                    group.append(
                        (
                            verified,
                            *pair_rule(notification, verified, tolerance_minutes=tolerance_minutes),
                        )
                    )
    viable: dict[str, list[str]] = defaultdict(list)
    for key, pairs in candidates.items():
        for other, decision, _ in pairs:
            if decision != "no link":
                viable[key].append(other.key)
                viable[other.key].append(key)
    # Walk only to mark competing components. This never creates a merged event.
    tainted: set[str] = set()
    visited: set[str] = set()
    for key in viable:
        if key in visited:
            continue
        component: set[str] = set()
        pending = [key]
        while pending:
            node = pending.pop()
            if node in component:
                continue
            component.add(node)
            pending.extend(viable[node])
        visited.update(component)
        if any(len(viable[node]) > 1 for node in component):
            tainted.update(component)
    groups: list[dict[str, object]] = []
    links: dict[str, str] = {}
    covered: set[str] = set()
    for row in rows:
        if row.key not in candidates:
            continue
        pairs = candidates[row.key]
        possible = [
            (other, decision, reason) for other, decision, reason in pairs if decision != "no link"
        ]
        decision, reason = "no link", "no compatible verified row in the candidate block"
        if possible:
            other, pair_decision, pair_reason = possible[0]
            if row.key in tainted:
                decision, reason = (
                    "abstain",
                    "multiple plausible cross-stage matches; no forced merge",
                )
            else:
                decision, reason = pair_decision, pair_reason
            if decision == "link":
                links[row.key] = other.key
        if issue := evidence_issue(row):
            decision, reason = "abstain", issue
            links.pop(row.key, None)
        member_keys = [row.key, *[other.key for other, _, _ in pairs]]
        covered.update(member_keys)
        groups.append(
            {
                "group_id": row.key,
                "source_rows": member_keys,
                "decision": decision,
                "reason": reason,
                "tool_matched_verified_row": links.get(row.key, ""),
                "pair_decisions": [
                    {"source_row": other.key, "decision": d, "reason": r} for other, d, r in pairs
                ],
            }
        )
    for row in rows:
        if row.key not in covered:
            groups.append(
                {
                    "group_id": row.key,
                    "source_rows": [row.key],
                    "decision": "abstain" if evidence_issue(row) else "no link",
                    "reason": evidence_issue(row)
                    or "no notification candidate; source row retained",
                    "tool_matched_verified_row": "",
                    "pair_decisions": [],
                }
            )
    lookup = {row.key: row for row in rows}
    linked_verified = set(links.values())
    events: list[dict[str, object]] = []
    for row in rows:
        if row.key in linked_verified:
            continue
        members = [row, lookup[links[row.key]]] if row.key in links else [row]
        fields = field_provenance(members)
        conflicts = [
            field
            for field, audit in fields.items()
            if isinstance(audit, dict) and audit["state"] == "conflicting"
        ]
        events.append(
            {
                "candidate_event_id": row.key,
                "source_rows": [r.key for r in members],
                "fields": fields,
                "conflicting_fields": conflicts,
                "flags": sorted({flag for r in members for flag in r.flags}),
            }
        )
    counts = Counter(str(group["decision"]) for group in groups)
    verified_rows = [
        row for row in rows if row.get("reporterClass") == VERIFIED and not row.retracted
    ]
    usable = [
        row
        for row in verified_rows
        if permittee(row) and row.day is not None and known(row.get("eventType"))
    ]
    proxy = len({(permittee(row), normal(row.get("eventType")), row.day) for row in usable})
    summary: dict[str, object] = {
        "attribution": output_attribution(),
        "snapshot_sha256": digest,
        "rule_version": RULE_VERSION,
        "source_report_rows": len(rows),
        "cso_source_report_rows": sum("CSO" in row.get("eventType") for row in rows),
        "source_event_types": dict(sorted(Counter(row.get("eventType") for row in rows).items())),
        "candidate_discharge_events": len(events),
        "decision_groups": len(groups),
        "ambiguous_component_rows": len(tainted),
        "unmerged_source_rows": len(rows) - 2 * counts["link"],
        "links": counts["link"],
        "no_links": counts["no link"],
        "abstentions": counts["abstain"],
        "conflicting_candidate_events": sum(bool(event["conflicting_fields"]) for event in events),
        "high_volume_review_rows": sum("high_volume_review" in row.flags for row in rows),
        "explicit_retraction_rows": sum(row.retracted for row in rows),
        "invalid_coordinate_review_rows": sum(
            any(
                flag in row.flags
                for flag in ("invalid_latitude_review", "invalid_longitude_review")
            )
            for row in rows
        ),
        "regulator_event_count": None,
        "regulator_definition_proxy": {
            "groups": proxy,
            "eligible_verified_rows": len(usable),
            "missing_key_rows": len(verified_rows) - len(usable),
            "rule": (
                "Verified rows grouped by permittee name (ID fallback), normalised event type "
                "and incident date; explicit retractions excluded."
            ),
            "limit": (
                "Not an official count. Retraction and revision histories are not supplied. "
                "Zero volume is not inferred as retracted."
            ),
        },
        "human_check_status": "not checked",
        "automatic_link_precision": None,
        "counting_note": (
            "Decision groups may overlap source rows. Candidate events partition "
            "every row; ambiguous rows remain separate. Counts are hypotheses, "
            "not established physical discharges."
        ),
    }
    return LinkageResult(rows, groups, events, summary)


def write_linkage(result: LinkageResult, local: Path, summary_path: Path) -> None:
    """Write detailed source/provenance only to the local processed directory."""
    local.mkdir(parents=True, exist_ok=True)
    for name, values in [
        (
            "source_rows",
            [
                {
                    "source_row": r.key,
                    "csv_record_ordinal": r.ordinal,
                    "raw": r.raw,
                    "clock_status": r.clock_status,
                    "flags": r.flags,
                }
                for r in result.rows
            ],
        ),
        ("decisions", result.groups),
        ("candidate_events", result.events),
    ]:
        (local / f"{name}.jsonl").write_text(
            "".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values),
            encoding="utf-8",
        )
    summary_path.write_text(
        json.dumps(result.summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def link_snapshot(path: Path, pinned: bool = True) -> LinkageResult:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if pinned and digest != EXPECTED_DOWNLOAD_SHA256:
        raise ValueError("Linkage snapshot SHA-256 mismatch")
    rows = load_source_rows(path)
    required = {
        "incidentId",
        "incidentNumber",
        "parentIncidentId",
        "reporterClass",
        "reportingType",
        "eventType",
        "permiteeName",
        "permiteeId",
        "outfallId",
        "location",
        "latitude",
        "longitude",
        "incidentDate",
        "incidentTime",
        "amPm",
        "submittedDate",
        "volumnOfEvent",
    }
    if pinned and (
        len(rows) != 18759
        or sum("CSO" in row.get("eventType") for row in rows) != 16720
        or not rows
        or not required <= rows[0].raw.keys()
    ):
        raise ValueError("Linkage snapshot headers or row counts mismatch")
    return build_linkage(rows, digest)
