"""Command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cso_insight.config import PipelineConfig
from cso_insight.pipeline import run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cso-insight",
        description="Data-driven analysis of combined sewer overflow discharges",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Download data and regenerate all results")
    run_parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Project root directory",
    )
    run_parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Use cached raw data if present",
    )

    args = parser.parse_args(argv)
    if args.command == "run":
        config = PipelineConfig.from_root(args.root.resolve())
        timings = run_pipeline(config, skip_download=args.skip_download)
        print(f"Pipeline complete in {timings['total_s']:.1f}s")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
