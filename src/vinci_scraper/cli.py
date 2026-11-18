"""Command-line entry point (`vinci`).

Each feature adds its own subcommand here. Crawl options (--host, --max-pages,
--dry-run) are tracked in SCR-08.
"""

import argparse
from collections.abc import Sequence

from vinci_scraper import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vinci", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_subparsers(dest="command", metavar="COMMAND")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
