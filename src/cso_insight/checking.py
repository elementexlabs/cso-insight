"""Reproducible local check sheets with explicitly declared reviewer modes."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import cast

from cso_insight.linkage import LinkageResult

SAMPLE_SEED = 20261010
HUMAN_COLUMNS = [
    "human_verdict",
    "human_matched_verified_row",
    "human_note",
    "checker_name",
    "checked_date",
]
MACHINE_COLUMNS = [
    "group_id",
    "stratum",
    "source_rows_json",
    "tool_decision",
    "tool_reason",
    "tool_matched_verified_row",
    "pair_decisions_json",
]
COLUMNS = MACHINE_COLUMNS + HUMAN_COLUMNS
REVIEW_MODES = {
    "human": "assisted, unblinded human check",
    "ai-agent": (
        "assisted, unblinded check by independent AI review agents directed by Amir Daneshpajouh"
    ),
}


def _review_label(rows: list[dict[str, str]], review_mode: str | None) -> str:
    if review_mode is not None:
        if review_mode not in REVIEW_MODES:
            raise ValueError("Review mode must be human or ai-agent")
        return REVIEW_MODES[review_mode]
    declarations = [
        re.findall(r"\[review-mode=(human|ai-agent)\]", row["checker_name"]) for row in rows
    ]
    if (
        not declarations
        or any(len(modes) != 1 for modes in declarations)
        or len({modes[0] for modes in declarations}) != 1
    ):
        raise ValueError(
            "Review mode is not explicit and consistent in every checker_name. "
            "Pass --review-mode human or --review-mode ai-agent, or put the same "
            "[review-mode=human] or [review-mode=ai-agent] marker in every checker_name."
        )
    return REVIEW_MODES[declarations[0][0]]


def _csv_text(rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def sample_groups(result: LinkageResult) -> tuple[list[dict[str, str]], dict[str, object]]:
    """Hash-rank groups in exclusive strata; shortages redistribute in fixed order."""
    buckets: dict[str, list[dict[str, object]]] = {
        "easy_pairs": [],
        "hard_cases": [],
        "abstentions": [],
    }
    lookup = {row.key: row for row in result.rows}
    conflicting = {
        str(event["candidate_event_id"]) for event in result.events if event["conflicting_fields"]
    }
    for group in result.groups:
        rows = [lookup[key] for key in cast(list[str], group["source_rows"])]
        stratum = (
            "abstentions"
            if group["decision"] == "abstain"
            else "easy_pairs"
            if group["decision"] == "link"
            and group["group_id"] not in conflicting
            and not any(row.flags for row in rows)
            else "hard_cases"
        )
        buckets[stratum].append(group)
    digest = str(result.summary["snapshot_sha256"])

    def rank(group: dict[str, object]) -> str:
        return hashlib.sha256(f"{SAMPLE_SEED}:{digest}:{group['group_id']}".encode()).hexdigest()

    for bucket in buckets.values():
        bucket.sort(key=rank)
    quotas = {"easy_pairs": 40, "hard_cases": 30, "abstentions": 30}
    selected: list[tuple[str, dict[str, object]]] = []
    for name, quota in quotas.items():
        selected.extend((name, group) for group in buckets[name][:quota])
    deficit = min(100, len(result.groups)) - len(selected)
    for name, quota in quotas.items():
        extra = buckets[name][quota : quota + deficit]
        selected.extend((name, group) for group in extra)
        deficit -= len(extra)
    sheet: list[dict[str, str]] = []
    for stratum, group in selected:
        rows = [lookup[key] for key in cast(list[str], group["source_rows"])]
        sheet.append(
            {
                "group_id": str(group["group_id"]),
                "stratum": stratum,
                "source_rows_json": json.dumps(
                    [
                        {
                            "source_row": row.key,
                            "csv_record_ordinal": row.ordinal,
                            "raw": row.raw,
                            "clock_status": row.clock_status,
                            "flags": row.flags,
                        }
                        for row in rows
                    ],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "tool_decision": str(group["decision"]),
                "tool_reason": str(group["reason"]),
                "tool_matched_verified_row": str(group["tool_matched_verified_row"]),
                "pair_decisions_json": json.dumps(
                    group["pair_decisions"], ensure_ascii=False, sort_keys=True
                ),
                **dict.fromkeys(HUMAN_COLUMNS, ""),
            }
        )
    metadata: dict[str, object] = {
        "seed": SAMPLE_SEED,
        "algorithm": "SHA-256 ranking of seed:snapshot hash:group ID within each exclusive stratum",
        "requested_quotas": quotas,
        "eligible_strata": {name: len(bucket) for name, bucket in buckets.items()},
        "sample_strata": dict(Counter(row["stratum"] for row in sheet)),
        "sample_groups": len(sheet),
        "redistribution_order": list(quotas),
        "unit": "decision groups; source rows can occur in more than one group",
        "human_check_status": "not checked",
        "precision": None,
    }
    return sheet, metadata


def machine_digest(rows: list[dict[str, str]]) -> str:
    values = [{field: row[field] for field in MACHINE_COLUMNS} for row in rows]
    return hashlib.sha256(
        json.dumps(values, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def read_sheet(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != COLUMNS:
            raise ValueError("Check-sheet columns changed")
        rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("Malformed check-sheet row")
    return rows


def render_sheet(rows: list[dict[str, str]], metadata: dict[str, object]) -> str:
    """Static readable page; CSV is the editable record of reviewer judgements."""
    pieces: list[str] = []
    for row in rows:
        source = cast(list[dict[str, object]], json.loads(row["source_rows_json"]))
        fields = [
            "source_row",
            "incidentId",
            "incidentNumber",
            "parentIncidentId",
            "reporterClass",
            "reportingType",
            "permiteeName",
            "permiteeId",
            "eventType",
            "outfallId",
            "location",
            "latitude",
            "longitude",
            "incidentDate",
            "incidentTime",
            "amPm",
            "submittedDate",
            "volumnOfEvent",
            "rainfallData",
            "hours",
            "minutes",
        ]
        header = "".join(f"<th scope='col'>{html.escape(field)}</th>" for field in fields)
        records: list[str] = []
        for item in source:
            raw = cast(dict[str, str], item["raw"])
            values = {**raw, "source_row": str(item["source_row"])}
            records.append(
                "<tr>"
                + "".join(f"<td>{html.escape(values.get(field, ''))}</td>" for field in fields)
                + "</tr>"
            )
        humans = "".join(
            f"<tr><th scope='row'>{field}</th><td>{html.escape(row[field])}</td></tr>"
            for field in HUMAN_COLUMNS
        )
        pieces.append(
            f"<section><h2>{html.escape(row['group_id'])}: {row['stratum']}</h2>"
            f"<p>Tool: {html.escape(row['tool_decision'])}. "
            f"{html.escape(row['tool_reason'])}. "
            f"Proposed verified row: {html.escape(row['tool_matched_verified_row'])}.</p>"
            f"<table><thead><tr>{header}</tr></thead>"
            f"<tbody>{''.join(records)}</tbody></table>"
            "<details><summary>Pair evidence and all source fields</summary>"
            f"<pre>{html.escape(row['pair_decisions_json'])}\n"
            f"{html.escape(json.dumps(source, ensure_ascii=False, indent=2))}</pre>"
            f"</details><table>{humans}</table></section>"
        )
    return (
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Discharge linkage check sheet</title><style>"
        "body{font:16px system-ui;margin:2rem;line-height:1.5}"
        "table{border-collapse:collapse;display:block;overflow:auto;margin-bottom:1rem}"
        "td,th{border:1px solid #777;padding:.4rem;text-align:left}"
        "pre{white-space:pre-wrap}section{margin:3rem 0}th{background:#eee}</style>"
        "<h1>Discharge linkage check sheet</h1><p>Local source records. "
        "Edit only the five reviewer columns in adjudication.csv. "
        "The historical human_* column names are retained for compatibility. "
        "Reviewer verdicts have not been supplied by the program. "
        "A filled CSV remains the authoritative record; this page shows its saved state "
        "at generation time.</p><p>Seed "
        + str(metadata["seed"])
        + ". Sample strata: "
        + html.escape(str(metadata["sample_strata"]))
        + ". Precision is unavailable until checking is complete; "
        "declare human or ai-agent review mode when scoring.</p>" + "".join(pieces) + "</html>"
    )


def write_sample(result: LinkageResult, local: Path) -> dict[str, object]:
    rows, metadata = sample_groups(result)
    manifest = {
        "snapshot_sha256": result.summary["snapshot_sha256"],
        "rule_version": result.summary["rule_version"],
        "machine_sha256": machine_digest(rows),
        "machine_rows": [{field: row[field] for field in MACHINE_COLUMNS} for row in rows],
        "sampling": metadata,
    }
    manifest_path, sheet_path = local / "sample_manifest.json", local / "adjudication.csv"
    local.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        if json.loads(manifest_path.read_text()) != manifest:
            raise ValueError(
                "Existing sample manifest differs; preserve it and use a separate run directory"
            )
        saved = read_sheet(sheet_path)
        if machine_digest(saved) != manifest["machine_sha256"]:
            raise ValueError("Existing check sheet has changed machine fields")
        rows = saved
    else:
        if sheet_path.exists():
            raise ValueError("Existing check sheet has no manifest; refusing to overwrite")
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        sheet_path.write_text(_csv_text(rows), encoding="utf-8", newline="")
    (local / "adjudication.html").write_text(render_sheet(rows, metadata), encoding="utf-8")
    return metadata


def score_sheet(
    sheet: Path,
    manifest_path: Path,
    expected_manifest_sha256: str,
    review_mode: str | None = None,
) -> dict[str, object]:
    """Return no precision for incomplete checks; validate every machine field first."""
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != expected_manifest_sha256:
        raise ValueError("Manifest does not match the trusted build-receipt SHA-256")
    rows = read_sheet(sheet)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if set(manifest) != {
        "snapshot_sha256",
        "rule_version",
        "machine_sha256",
        "machine_rows",
        "sampling",
    }:
        raise ValueError("Manifest schema changed")
    reference = cast(list[dict[str, str]], manifest["machine_rows"])
    if len({row["group_id"] for row in reference}) != len(reference):
        raise ValueError("Duplicate manifest group IDs")
    for row in reference:
        if (
            set(row) != set(MACHINE_COLUMNS)
            or row["stratum"] not in {"easy_pairs", "hard_cases", "abstentions"}
            or row["tool_decision"] not in {"link", "no link", "abstain"}
        ):
            raise ValueError("Invalid manifest machine schema")
        if not row["group_id"].startswith(str(manifest["snapshot_sha256"]) + ":row-"):
            raise ValueError("Manifest source identity mismatch")
    if (
        machine_digest(reference) != manifest["machine_sha256"]
        or machine_digest(rows) != manifest["machine_sha256"]
    ):
        raise ValueError("Machine fields do not match the sample manifest")
    review_label = _review_label(rows, review_mode)
    complete: list[dict[str, str]] = []
    for original in rows:
        row = {**original, **{field: original[field].strip() for field in HUMAN_COLUMNS}}
        verdict = row["human_verdict"]
        if not verdict:
            if any(row[field].strip() for field in HUMAN_COLUMNS[1:]):
                raise ValueError("Checker details without a verdict")
            continue
        if verdict not in {"link", "no link", "unresolved"}:
            raise ValueError("Reviewer verdict must be link, no link or unresolved")
        if not row["checker_name"].strip():
            raise ValueError("A checked verdict needs a checker name")
        date.fromisoformat(row["checked_date"])
        target = row["human_matched_verified_row"]
        source = cast(list[dict[str, object]], json.loads(row["source_rows_json"]))
        notification = any(
            item["source_row"] == row["group_id"]
            and cast(dict[str, str], item["raw"]).get("reporterClass")
            == "Public Notification Report"
            for item in source
        )
        verified_keys = {
            str(item["source_row"])
            for item in source
            if cast(dict[str, str], item["raw"]).get("reporterClass") == "Verified Data Report"
        }
        if verdict == "link" and (not notification or target not in verified_keys):
            raise ValueError("A reviewer link needs an exact listed verified-row key")
        if verdict != "link" and target:
            raise ValueError("Only a reviewer link can have a matched verified-row key")
        if (
            verdict == "unresolved"
            or (
                row["tool_decision"] != "abstain"
                and (
                    verdict != row["tool_decision"]
                    or (verdict == "link" and target != row["tool_matched_verified_row"])
                )
            )
        ) and not row["human_note"].strip():
            raise ValueError("A failure or unresolved case needs a note")
        complete.append(row)
    ready = len(complete) == len(rows) and bool(rows)
    automatic = [row for row in complete if row["tool_decision"] == "link"]
    resolved_links = [row for row in automatic if row["human_verdict"] != "unresolved"]
    correct = sum(
        row["human_verdict"] == "link"
        and row["human_matched_verified_row"] == row["tool_matched_verified_row"]
        for row in resolved_links
    )
    failures = [
        row["group_id"]
        for row in complete
        if row["tool_decision"] != "abstain"
        and row["human_verdict"] != "unresolved"
        and (
            row["tool_decision"] != row["human_verdict"]
            or (
                row["human_verdict"] == "link"
                and row["human_matched_verified_row"] != row["tool_matched_verified_row"]
            )
        )
    ]
    return {
        "status": "complete" if ready else "incomplete",
        "review_mode": review_label,
        "trusted_manifest_sha256": expected_manifest_sha256,
        "sample_groups": len(rows),
        "checked_groups": len(complete),
        "sample_strata": dict(Counter(row["stratum"] for row in rows)),
        "sample_abstention_rate": sum(row["tool_decision"] == "abstain" for row in rows) / len(rows)
        if rows
        else None,
        "sample_automatic_link_precision": correct / len(resolved_links)
        if ready and resolved_links and len(resolved_links) == len(automatic)
        else None,
        "automatic_links_checked": len(automatic) if ready else None,
        "automatic_links_unresolved": len(automatic) - len(resolved_links) if ready else None,
        "failure_count": len(failures) if ready else None,
        "failure_group_ids": failures if ready else None,
        "human_unresolved_groups": sum(row["human_verdict"] == "unresolved" for row in complete)
        if ready
        else None,
        "checkers_and_dates": sorted(
            {(row["checker_name"], row["checked_date"]) for row in complete}
        )
        if ready
        else None,
        "limit": (
            "Stratified sample results only. No population precision, "
            "recall or water benefit is inferred."
        ),
    }
