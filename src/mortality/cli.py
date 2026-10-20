"""Command-line entry point: ``uv run mortality <command>``."""

from __future__ import annotations

import argparse
import sys

from mortality import __version__
from mortality.config import MissingCredentialsError, find_rscript, get_paths, hmd_credentials


def cmd_doctor(_: argparse.Namespace) -> int:
    """Check that the environment is ready: paths, credentials and R."""
    paths = get_paths()
    ok = True

    print(f"Mortality Table Builder v{__version__}")
    print(f"  Python      {sys.version.split()[0]}")
    print(f"  Project     {paths.root}")
    print(f"  Data        {paths.data}")
    db_state = "exists" if paths.database.exists() else "not built yet"
    print(f"  Database    {paths.database}  ({db_state})")

    try:
        creds = hmd_credentials()
        print(f"  HMD login   configured for {creds.username}")
    except MissingCredentialsError:
        print("  HMD login   MISSING: copy .env.example to .env and fill it in")
        ok = False

    rscript = find_rscript()
    print(f"  Rscript     {rscript or 'not found (only needed for the R models)'}")

    print("\nAll set." if ok else "\nSome items need attention (see above).")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mortality", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check paths, credentials and tools")
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
