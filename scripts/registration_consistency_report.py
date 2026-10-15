"""Print registration consistency counts.

The report is read-only. It does not create enrollments, cancel them, or
rewrite students.enrolled_courses. Pass the database explicitly. The
application default database is not used.

    .\\.venv\\Scripts\\python.exe scripts\\registration_consistency_report.py --uri mongodb://localhost:27017 --database bvonix_test_registration

Write mode is refused for every database, including a test database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only registration consistency counts.")
    parser.add_argument("--uri", required=False, help="MongoDB connection string. There is no default.")
    parser.add_argument("--database", required=False, help="Database name. There is no default.")
    parser.add_argument("--write", action="store_true", help="Rejected. This report cannot change records.")
    return parser


def refuse_write(database: str | None) -> None:
    """Enrollment rows and course lists are not changed by this report."""
    name = database or "(no database selected)"
    raise SystemExit(f"Refusing to write enrollment records in {name}. This report is read-only.")


async def _run(uri: str, database: str) -> dict:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from motor.motor_asyncio import AsyncIOMotorClient

    from app.services.registration_consistency import registration_consistency_report

    client = AsyncIOMotorClient(uri)
    try:
        return await registration_consistency_report(client[database])
    finally:
        client.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.write:
        refuse_write(args.database)
    if not args.uri or not args.database:
        print("Pass --uri and --database. No database is selected by default.", file=sys.stderr)
        return 2
    report = asyncio.run(_run(args.uri, args.database))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
