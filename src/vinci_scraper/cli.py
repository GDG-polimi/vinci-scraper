"""Command-line entry point (`vinci`).

Each feature adds its own subcommand here. Crawl options (--host, --max-pages,
--dry-run) are tracked in SCR-08.
"""

import argparse
from collections.abc import Sequence
from contextlib import closing

from vinci_scraper import __version__, db

DEFAULT_DB = "data/vinci.sqlite"


def cmd_db_migrate(args: argparse.Namespace) -> int:
    with closing(db.connect(args.db)) as conn:
        applied = db.migrate(conn)
        version = db.schema_version(conn)
    if applied:
        print(f"applied migrations: {', '.join(map(str, applied))} (schema version {version})")
    else:
        print(f"already up to date (schema version {version})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vinci", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    db_parser = commands.add_parser("db", help="manage the SQLite database")
    db_commands = db_parser.add_subparsers(dest="db_command", metavar="COMMAND", required=True)
    migrate = db_commands.add_parser("migrate", help="create or upgrade the schema")
    migrate.add_argument("--db", default=DEFAULT_DB, help=f"database path (default: {DEFAULT_DB})")
    migrate.set_defaults(handler=cmd_db_migrate)

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
