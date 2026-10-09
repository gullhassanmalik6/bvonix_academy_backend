"""Rebuild students.enrolled_courses from non-cancelled enrollments.

The default run is a dry run. It does not select a database by itself and it
does not read the application MONGODB_URI or MONGODB_DB settings.

    .\\.venv\\Scripts\\python.exe scripts\\reconcile_enrolled_courses.py --uri mongodb://localhost:27017 --database bvonix_test_registration

Write mode is a separate opt-in. It still requires the uri and database:

    .\\.venv\\Scripts\\python.exe scripts\\reconcile_enrolled_courses.py --uri mongodb://localhost:27017 --database bvonix_test_registration --write

The command refuses APP_ENV production or prod, the database names
bvonix_academy, production, and prod, any name containing prod, and any name
that does not start with bvonix_test. A refused target fails before a client
is opened.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

FORBIDDEN_ENVIRONMENTS = {"production", "prod"}
FORBIDDEN_DATABASE_NAMES = {"bvonix_academy", "production", "prod"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rebuild compatibility course lists from enrollments.")
    parser.add_argument("--uri", required=False, help="MongoDB connection string. There is no default.")
    parser.add_argument("--database", required=False, help="Database name. There is no default.")
    parser.add_argument("--write", action="store_true", help="Replace course lists. Omit this flag for a dry run.")
    return parser


def assert_reconciliation_target(database: str, app_env: str) -> None:
    """Refuse a production-like target before any client is opened."""
    name = database.strip()
    environment = app_env.strip().lower()
    folded = name.lower()
    if (
        environment in FORBIDDEN_ENVIRONMENTS
        or not name
        or folded in FORBIDDEN_DATABASE_NAMES
        or "prod" in folded
        or not folded.startswith("bvonix_test")
    ):
        raise SystemExit("Refusing to reconcile registration lists for this database.")


def command_exit_code(result: dict) -> int:
    """A partial failure is not a successful reconciliation."""
    return 0 if result.get("completed") else 1


async def _run(uri: str, database: str, *, write: bool) -> dict:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from motor.motor_asyncio import AsyncIOMotorClient

    from app.services.registration_consistency import reconcile_registration_lists

    client = AsyncIOMotorClient(uri)
    try:
        return await reconcile_registration_lists(client[database], write=write)
    finally:
        client.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.uri or not args.database:
        print("Pass --uri and --database. No database is selected by default.", file=sys.stderr)
        return 2
    assert_reconciliation_target(args.database, os.environ.get("APP_ENV", ""))
    result = asyncio.run(_run(args.uri, args.database, write=args.write))
    print(json.dumps(result, indent=2, sort_keys=True))
    return command_exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
