# Local release procedure

This repository is a bounded Massachusetts public-data engineering work sample.
It establishes neither firm client references nor regional operational validation.
No remote CI receipt or flagship-readiness verdict is asserted.

## Reproducible checks

Supported installation contract: Python 3.11 and 3.12. Install pinned dependencies
with `pip install -r requirements-lock.txt`, then the checkout with
`pip install --no-deps -e .`. Build tooling is separately resolved by pip's isolated
build; the analysis and check-tool dependencies are pinned, not hash-locked wheels.

Run `python -m pytest --cov=cso_insight --cov-fail-under=90`,
`ruff check src tests scripts`, `mypy src`, `pyright`, and `mkdocs build --strict`.
CI additionally runs `cso-insight run --root .` and
`python scripts/check_publication.py` to check the generated metric/cohort and browser
contracts. A changed live source can fail acquisition; this is an explicit integrity
stop, not permission to update the pin. See DATA_MANIFEST.md for snapshot recovery.

One command regenerates analytical outputs, RESULTS.md, and the complete browser
results/methodology/manifest pages: `cso-insight run --root .`.
For a permitted retained snapshot at the declared raw path, use the documented
hash-verified recovery command `cso-insight run --root . --skip-download`.
Source prose is maintained manually; numeric metric/cohort copies are generated.
Elapsed time, hardware string and tiny aggregate summation differences can vary.
There is no byte-identity guarantee for all outputs and no measured memory ceiling.

## Separate public history

Preserve the original history. Its commits retain authorized maintainer attribution,
an old absolute lock path, record-linked QA derivatives and a scatter display.
Do not publish that history under the selected-tree-only, aggregate-only requirement.

Every commit, including the public candidate, uses the owner's author and committer identity inherited from the approved source commit's Git metadata, while ElementeX Labs Inc. remains the publisher in package metadata, CITATION.cff and the licence notice, with personal identifiers confined to commit metadata and ordinary scholarly citations retained.

Run `python scripts/prepare_public.py` to create state/public.bundle with a single
owner-attribution snapshot commit on `publication-r6`, no inherited history, and no internal
milestone/remediation reports. The source commit's author and committer must match;
the scanner verifies both candidate headers against that identity without embedding
the owner's name or email in shipped files. CITATION.cff retains the organizational author, ElementeX Labs Inc.
No refs in the original repository are rewritten and nothing is pushed.
SOURCE_MANIFEST.json in the snapshot hashes its copied files; the adjacent
public.scan.json records the exact release commit, bundle hash, complete reachable
history scan and git fsck result. The bounded scan checks absolute home paths,
common credential signatures, credential URLs, literal em dashes and generated-work
attribution; it does not guarantee that every possible encoded secret is absent.
A source/check environment manifest accompanies local verification in the round 5
report. Tagging, remote CI and publication remain separate actions.
