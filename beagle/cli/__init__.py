from __future__ import annotations

import sys

from ..errors import BeagleError
from .commands import COMMANDS
from .parser import build_parser

__all__ = ["main", "COMMANDS", "build_parser"]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    try:
        return COMMANDS[args.command](args)
    except BeagleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        return 130
