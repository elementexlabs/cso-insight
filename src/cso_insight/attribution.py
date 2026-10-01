"""Consistent provenance and rights boundary for generated artifacts."""

from cso_insight.config import DEFAULT_MA_CSO_URL, EXPECTED_DOWNLOAD_SHA256


def output_attribution() -> dict[str, str]:
    return {
        "source": DEFAULT_MA_CSO_URL,
        "source_owner": "Massachusetts EEA / MassDEP; archived by AMEND",
        "snapshot_sha256": EXPECTED_DOWNLOAD_SHA256,
        "code_license": "Apache-2.0",
        "design_license": "CC BY 4.0 (original documentation and figure design only)",
        "data_rights": "Factual aggregate summaries; upstream rights remain with their owners.",
        "disclosure": "No report identifiers or individual measurement pairs in public outputs.",
    }
