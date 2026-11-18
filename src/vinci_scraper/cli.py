"""Command-line entry point (`vinci`).

Each feature adds its own subcommand here. Crawl options (--host, --max-pages,
--dry-run) are tracked in SCR-08.
"""

import argparse
from collections.abc import Sequence
from contextlib import closing

import yaml
from pydantic import ValidationError

from vinci_scraper import __version__, db
from vinci_scraper.config import DEFAULT_CONFIG, load_config

DEFAULT_DB = "data/vinci.sqlite"


def cmd_config_check(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        print(f"invalid config {args.config}:\n{exc}")
        return 1
    for name, host in config.hosts.items():
        state = "enabled" if host.enabled else "disabled"
        print(f"{name}: {state}, {len(host.allow)} allowed / {len(host.deny)} denied prefixes")
    for url in args.urls:
        frequency = config.frequency_for(url)
        print(
            f"{'ALLOW' if frequency else 'DENY '} {url}" + (f" ({frequency})" if frequency else "")
        )
    return 0


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

    config_parser = commands.add_parser("config", help="inspect the host configuration")
    config_commands = config_parser.add_subparsers(
        dest="config_command", metavar="COMMAND", required=True
    )
    check = config_commands.add_parser(
        "check", help="validate the config; optionally test whether URLs are allowed"
    )
    check.add_argument("urls", nargs="*", metavar="URL", help="URLs to test against the allowlist")
    check.add_argument(
        "--config", default=DEFAULT_CONFIG, help=f"config path (default: {DEFAULT_CONFIG})"
    )
    check.set_defaults(handler=cmd_config_check)

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
