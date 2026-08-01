from __future__ import annotations

import argparse

from ..constants import DEFAULT_CONFIG_PATH

TOPICS = ["cli", "api", "config", "feedback", "comments"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="beagle", description="Contextual AI code reviewer")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="path to config.toml")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("serve", help="run the server")

    index = subparsers.add_parser("index", help="index the repository now")
    index.add_argument("--full", action="store_true", help="re-scan every file")

    subparsers.add_parser("doctor", help="show effective config and health")

    review = subparsers.add_parser("review", help="review a ref against the default base")
    review.add_argument("ref", nargs="?", help="branch, tag or sha to review")
    review.add_argument("--base", help="base ref (defaults to repo.default_base)")
    review.add_argument("--diff", help="review a unified diff from a file, or - for stdin")
    review.add_argument("--fresh", action="store_true", help="do not reuse a stored answer")
    review.add_argument("--format", choices=["pretty", "md", "json"], default="pretty")

    evaluate = subparsers.add_parser("eval", help="score Beagle against a golden diff set")
    evaluate.add_argument("path", nargs="?", default="evals/golden.json")
    evaluate.add_argument("--format", choices=["pretty", "json"], default="pretty")

    guide = subparsers.add_parser("guide", help="print the guide")
    guide.add_argument("topic", nargs="?", choices=TOPICS)
    return parser
