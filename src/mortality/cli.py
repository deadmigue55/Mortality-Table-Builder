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


def cmd_ingest_inegi(args: argparse.Namespace) -> int:
    """Download INEGI death microdata and convert it to Parquet."""
    from mortality.ingest import inegi  # imported here so `doctor` stays fast

    years = inegi.parse_years(args.years)
    failed: list[int] = []
    for year in years:
        try:
            print(f"[{year}] downloading...")
            result = inegi.download_year(year, force=args.force)
            note = "already downloaded" if result.skipped else f"{result.bytes / 1e6:.1f} MB"
            print(f"[{year}] ZIP ready ({note})")
            if args.no_process:
                continue
            print(f"[{year}] converting to Parquet (takes a minute)...")
            out = inegi.process_year(year, force=args.force)
            print(f"[{year}] wrote {out}")
        except FileNotFoundError as err:
            print(f"[{year}] SKIPPED: {err}")
            failed.append(year)
    if failed:
        print(f"\nNot available automatically: {', '.join(map(str, failed))}")
        return 1
    return 0


def cmd_ingest_conapo(args: argparse.Namespace) -> int:
    """Download CONAPO population and convert it to Parquet."""
    from mortality.ingest import conapo

    print("downloading CONAPO ZIP (about 80 MB)...")
    result = conapo.download(force=args.force)
    print(
        "ZIP ready"
        + (" (already downloaded)" if result.skipped else f" ({result.bytes / 1e6:.1f} MB)")
    )
    if args.no_process:
        return 0
    print("converting Excel files to Parquet...")
    for key, path in conapo.process(force=args.force).items():
        print(f"  {key}: {path}")
    return 0


def cmd_ingest_hmd(args: argparse.Namespace) -> int:
    """Download Human Mortality Database tables for comparison countries."""
    from mortality.ingest import hmd

    countries = [c.upper() for c in args.countries]
    print(f"logging in to mortality.org and downloading {len(countries)} countries...")
    results = hmd.download_countries(countries, force=args.force)
    new = sum(not r.skipped for r in results)
    print(f"{len(results)} files ready ({new} new)")
    if args.no_process:
        return 0
    for name, path in hmd.process(countries).items():
        print(f"  {name}: {path}")
    return 0


def cmd_ingest_soa(args: argparse.Namespace) -> int:
    """Download the curated SOA / Mexican tables from mort.soa.org."""
    from mortality.ingest import soa

    print(f"downloading {len(soa.TABLES)} tables from mort.soa.org...")
    results = soa.download_all(force=args.force)
    print(f"{len(results)} tables ready ({sum(not r.skipped for r in results)} new)")
    if args.no_process:
        return 0
    for name, path in soa.process().items():
        print(f"  {name}: {path}")
    return 0


def cmd_ingest_cnsf(args: argparse.Namespace) -> int:
    """Download and parse the CNSF 2013 regulatory tables (CUSF Annex 5.3.3-a)."""
    import pandas as pd

    from mortality.ingest import cnsf

    print("downloading CNSF Annex 5.3.3-a (online circular + gob.mx PDF)...")
    cnsf.download(force=args.force)
    path = cnsf.process()
    rates = pd.read_parquet(path)
    print(f"  {len(rates)} rates in {rates.groupby(['table', 'variant']).ngroups} tables -> {path}")
    print(f"  annex last modified (DOF): {rates['annex_modified'].iloc[0]}")

    pdf = get_paths().raw / cnsf.SOURCE / cnsf.PDF_FILE
    diff = cnsf.cross_check(rates, cnsf.parse_pdf_base_tables(pdf))
    print(f"  cross-check against the PDF, largest difference: {diff:g}")
    return 0 if diff < 1e-9 else 1


def cmd_ingest_inegi_cube(args: argparse.Namespace) -> int:
    """Import INEGI interactive-table exports (CSV or ZIP) saved from the browser."""
    from pathlib import Path

    from mortality.ingest import inegi_cube

    imported = inegi_cube.import_files([Path(p) for p in args.files])
    for item in imported:
        note = f"  <-- file was named {item.original_name!r}" if item.renamed else ""
        print(f"  registration year {item.year}: {item.download.bytes:,} bytes{note}")
    mislabeled = [i for i in imported if i.renamed]
    print(f"{len(imported)} tables imported -> {inegi_cube.process()}")
    if mislabeled:
        names = ", ".join(f"{i.original_name} is really {i.year}" for i in mislabeled)
        print(f"\nWARNING: check your export. {names}.")
    return 0


def cmd_db_build(_: argparse.Namespace) -> int:
    """Load every processed source into SQLite and run the data checks."""
    from mortality import validate, warehouse

    print("building the warehouse...")
    for table, rows in warehouse.build().items():
        print(f"  {table:<24}{rows:>12,} rows")
    return _print_checks(validate.validate())


def cmd_db_check(_: argparse.Namespace) -> int:
    """Re-run the data checks on the existing warehouse."""
    from mortality import validate

    return _print_checks(validate.validate())


def cmd_figures(args: argparse.Namespace) -> int:
    """Draw the README figures from the warehouse."""
    from pathlib import Path

    from mortality import figures

    for path in figures.build_all(Path(args.out)):
        print(f"  wrote {path}")
    return 0


def _print_checks(results) -> int:
    print("\ndata checks:")
    for r in results:
        detail = "" if r.violations in (None, 0) else f"  ({r.violations:,} violations)"
        print(f"  {r.status:<5} {r.name:<34}{r.what}{detail}")
    counts = {s: sum(r.status == s for r in results) for s in ("PASS", "WARN", "FAIL", "SKIP")}
    print(
        f"\n{counts['PASS']} passed, {counts['WARN']} warnings, "
        f"{counts['FAIL']} failed, {counts['SKIP']} skipped"
    )
    return 1 if counts["FAIL"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mortality", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check paths, credentials and tools")
    doctor.set_defaults(func=cmd_doctor)

    db = sub.add_parser("db", help="the warehouse")
    db_sub = db.add_subparsers(dest="action", required=True)
    db_sub.add_parser("build", help="load all sources and run checks").set_defaults(
        func=cmd_db_build
    )
    db_sub.add_parser("check", help="re-run the data checks").set_defaults(func=cmd_db_check)

    figs = sub.add_parser("figures", help="draw the README figures from the warehouse")
    figs.add_argument("--out", default="docs/img", help="output folder (default: docs/img)")
    figs.set_defaults(func=cmd_figures)

    ingest = sub.add_parser("ingest", help="download and prepare source data")
    sources = ingest.add_subparsers(dest="source", required=True)

    inegi = sources.add_parser("inegi", help="INEGI registered deaths (microdata)")
    inegi.add_argument(
        "--years", nargs="+", default=["2020-2024"], help="e.g. 2020-2024 or 2021 2023"
    )
    inegi.add_argument("--force", action="store_true", help="download and rebuild again")
    inegi.add_argument("--no-process", action="store_true", help="download only")
    inegi.set_defaults(func=cmd_ingest_inegi)

    conapo = sources.add_parser("conapo", help="CONAPO population 1950-2070")
    conapo.add_argument("--force", action="store_true", help="download and rebuild again")
    conapo.add_argument("--no-process", action="store_true", help="download only")
    conapo.set_defaults(func=cmd_ingest_conapo)

    from mortality.ingest.hmd import DEFAULT_COUNTRIES

    hmd = sources.add_parser("hmd", help="Human Mortality Database (needs a free login in .env)")
    hmd.add_argument(
        "--countries",
        nargs="+",
        default=list(DEFAULT_COUNTRIES),
        help="HMD country codes, e.g. USA CAN CHL ESP",
    )
    hmd.add_argument("--force", action="store_true", help="download and rebuild again")
    hmd.add_argument("--no-process", action="store_true", help="download only")
    hmd.set_defaults(func=cmd_ingest_hmd)

    soa = sources.add_parser("soa", help="SOA MORT tables, incl. Mexican ones (CNSF 2000-I, EMSSA)")
    soa.add_argument("--force", action="store_true", help="download and rebuild again")
    soa.add_argument("--no-process", action="store_true", help="download only")
    soa.set_defaults(func=cmd_ingest_soa)

    cube = sources.add_parser(
        "inegi-cube", help="INEGI interactive-table exports saved by hand (CSV or ZIP)"
    )
    cube.add_argument("files", nargs="+", help="exported .csv files or a .zip of them")
    cube.set_defaults(func=cmd_ingest_inegi_cube)

    cnsf = sources.add_parser("cnsf", help="CNSF 2013 regulatory tables (CUSF Annex 5.3.3-a)")
    cnsf.add_argument("--force", action="store_true", help="download again")
    cnsf.set_defaults(func=cmd_ingest_cnsf)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
