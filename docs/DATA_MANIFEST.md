# Data manifest

Inventory and rights assessment updated 2026-10-01. Public outputs are factual
aggregate summaries of utility-reported Massachusetts CSO report rows, with source
attribution. They are not independently verified physical discharges.

## Massachusetts feed

| Field | Value |
|---|---|
| Owner | Massachusetts EEA / MassDEP, archived by the Archive of Massachusetts Environmental Data (AMEND) |
| Acquisition | [AMEND CSV](https://openamend.org/data/EEADP_CSO.csv) |
| Source page | [EEA portal archive](https://openamend.org/data/EEADP_all.html) |
| Snapshot SHA-256 | `0e8a56ebf1870646431de7c1d326065fbcd9cd27f63132e0790e79eb5ef231c3` |
| Snapshot size | 5,114,767 bytes; 16,720 CSO report rows after event-type filter |
| Classes retained | Public Notification Report and Verified Data Report; other classes retained if present |
| Counting unit | Report rows; stages may produce multiple reports for a discharge |

The [AMEND dataset page](https://openamend.org/data/) describes a freely distributed
public-source database (checked 2026-10-01). No separate dataset-specific licence was
found in the reviewed page. A second check on 2026-10-11 found none either: the AMEND data page
and its about page state no licence, and the project's source repository
([nesanders/MAenvironmentaldata](https://github.com/nesanders/MAenvironmentaldata)) declares none
(GitHub repository licence field empty and no licence file, read 2026-10-11 00:35 PT).
We therefore treat the AMEND files as unlicensed copies of Massachusetts public records:
this repository ships no AMEND file, only the derived aggregates listed below, with attribution. The [MassDEP policies](https://www.mass.gov/info-details/massdep-site-policies)
provide a public-record reuse basis with copyright exceptions; direct access on
2026-10-01 returned 403, so no new blanket permission verification is asserted.
The exact shipped fields are computed counts by class/year/identifier, summed volumes,
aggregate flag-type counts, bootstrap intervals, support counts and evaluation
statistics. Our basis for these outputs is factual aggregation of public records,
not a grant to relicense the upstream database. No upstream prose, map tiles or
analysis implementation is copied. Attribution is retained in every JSON/HTML/PNG
output and in documentation; design licences apply to our original expression only.

## Disclosure inventory

| Material | Current public snapshot | Boundary |
|---|---|---|
| Raw CSV, normalized rows, model coefficients | Withheld; local ignored data directories | Acquire from source; no raw archive in the release |
| Event UUIDs, row-linked QA details, individual measurements | Withheld | QA JSON and HTML export flag counts only; counts can overlap |
| Individual rainfall/volume scatter | Withheld | Removed; only aggregate rankings displayed |
| Evaluation/cohort/timing JSON | Factual aggregates plus attribution | No event identifiers or individual measurement pairs |
| Ranking PNGs | Observed aggregate report counts/volume by identifier, with intervals and municipality context | Source/hash/rights metadata embedded; accompanying notice in results/ATTRIBUTION.md |
| HTML/Markdown | Aggregate metrics, methodology and cohort flow | Original text/design CC BY 4.0; upstream rights retained |
| Synthetic test fixtures | Original constructed examples | No client/private data |

Historical commits contained a record-linked QA export and an event-pair scatter;
current-tree withholding does not remove them from the original history. The clean
public snapshot procedure in RELEASE.md omits that history without rewriting it.

## Licence boundary

Code is Apache-2.0 (root LICENSE). Original documentation and figure design are
CC BY 4.0 (LICENSE-CC-BY-4.0.txt). These declarations do not license upstream data,
third-party works or database rights. Source facts are attributed to MassDEP via
AMEND; rights remain with their owners. Do not infer an unconditional dataset grant.

## Other referenced datasets and research

| Resource | Use and redistribution |
|---|---|
| [EPA ECHO](https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary) | Link/context only; no content shipped |
| [Metro Vancouver map](https://metrovancouver.org/services/liquid-waste/real-time-sewer-overflow-map) | Link/context only; no tiles, records or reports shipped |
| [NYC annual CSO report](https://www.nyc.gov/assets/dep/downloads/pdf/water/stormwater/spdes-bmp-cso-annual-report-2024.pdf) | Link only; PDF withheld |
| AMEND/SWMM/PySWMM research/software | Citations only; no upstream implementation or paper text shipped |

## Snapshot recovery

The live AMEND route refreshes; a hash pin detects changes but cannot ensure perpetual
availability. Preserve a lawful private copy of the exact snapshot with this digest.
If live acquisition no longer matches, obtain that snapshot from the data owner or
an independently permitted archive, place it at data/raw/ma_eea_cso.csv and run
`cso-insight run --root . --skip-download`. The pipeline verifies the same hash before
analysis. Never reseal a changed feed as this result. If no matching copy is available,
this analysis cannot be regenerated; report that acquisition limitation. The release
contains no raw snapshot and makes no immutable-download guarantee.


## Preservation during acquisition

`./scripts/download_data.sh [destination]` writes a temporary sibling, verifies the
pinned hash, then atomically swaps into a separate acquisition path. Its default is
`data/raw/ma_eea_cso.download.csv`. It refuses the frozen
`data/raw/ma_eea_cso.csv`, including aliases and hard links. Network/hash failures
preserve existing files. The Python pipeline also verifies a temporary download
before replacement; the helper never overwrites the frozen snapshot.

If the frozen path is absent, a permitted matching acquisition can be installed with
`test ! -e data/raw/ma_eea_cso.csv && cp -n data/raw/ma_eea_cso.download.csv data/raw/ma_eea_cso.csv`.
Then run `cso-insight run --root . --skip-download`, which verifies the hash again.
A changed feed requires a separately versioned analysis. Never change this pin to
make reproduction pass; recover a matching permitted snapshot or stop.
