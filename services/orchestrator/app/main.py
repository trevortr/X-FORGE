from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pydantic import ValidationError

from .client import ServiceClient
from .config import ConfigurationError, ConfigurationLoader
from .results import ResultWriter
from .runner import PipelineRunError, PipelineRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the X-FORGE feedback loop")
    parser.add_argument(
        "--pipeline",
        type=Path,
        default=Path("/config/pipeline.yaml"),
    )
    parser.add_argument(
        "--services",
        type=Path,
        default=Path("/config/services.yaml"),
    )
    parser.add_argument(
        "--run-name",
        help="subdirectory to create beneath the results root",
    )
    parser.add_argument(
        "--results-root",
        type=Path,
        help="parent directory for run output (default: results)",
    )
    return parser


def run_from_args(args: argparse.Namespace) -> int:
    configuration = ConfigurationLoader.load(
        args.pipeline,
        args.services,
        run_name_override=args.run_name,
        results_root_override=args.results_root,
    )
    writer = ResultWriter(configuration.output_dir)
    with ServiceClient(configuration.services, configuration.http) as client:
        result = PipelineRunner(configuration, client, writer).run()
    logging.getLogger(__name__).info(
        "run %s completed %d iteration(s); results: %s",
        result.run_id,
        result.completed_iterations,
        configuration.output_dir / "run.json",
    )
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        return run_from_args(build_parser().parse_args())
    except (ConfigurationError, ValidationError, PipelineRunError) as exc:
        logging.getLogger(__name__).error("orchestration failed: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
