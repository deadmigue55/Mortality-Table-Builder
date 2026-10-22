"""Command-line entry point: ``uv run mortality <command>``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

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


def cmd_ingest_cnsf_vi(args: argparse.Namespace) -> int:
    """Import the CNSF individual life statistics (Excel 2021+, Access 2018 to 2020)."""
    from mortality.ingest import cnsf_vi

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"not a folder: {folder}")
        return 1
    found = cnsf_vi.find_files(folder)
    if not found:
        print("no '<year> Vida Individual Bases.xlsx' or 'Vida_Ind_<year>.zip' files found")
        return 1
    print(f"importing {len(found)} yearly files ({min(found)} to {max(found)}) into data/raw...")
    cnsf_vi.import_folder(folder)
    print("parsing (the Excel files take a few minutes each; results are cached)...")
    for path in cnsf_vi.process(force=args.force, legacy=not args.skip_legacy):
        print(f"  {path}")
    return 0


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


def cmd_app_data(args: argparse.Namespace) -> int:
    """Build the shareable demo bundle the dashboard reads (no HMD data, no raw microdata)."""
    from pathlib import Path

    from mortality import demo, experience
    from mortality.config import get_paths

    paths = get_paths()
    inputs = experience.warehouse_inputs(__import__("sqlite3").connect(paths.database))
    if inputs is None:
        print("The warehouse lacks the tables the bundle needs. Run `mortality db build` first.")
        return 1
    q, state_smr, weights = inputs
    portfolio = experience.load_or_generate_portfolio(paths, q, state_smr, weights)
    out = Path(args.out)
    counts = demo.build_bundle(paths.database, out, portfolio.policies)
    for table, rows in counts.items():
        print(f"  {table:<36}{rows:>10,} rows")
    bad = demo.forbidden_in(out / "demo.sqlite")
    leaked = demo.hmd_rows_in(out / "demo.sqlite")
    if bad or leaked:
        print(f"Bundle must not hold {bad} or HMD rows ({leaked}).")
        return 1
    size = sum(f.stat().st_size for f in out.iterdir() if f.is_file()) / 1e6
    print(f"wrote {out} ({size:.1f} MB)")
    return 0


def cmd_export_excel(args: argparse.Namespace) -> int:
    """Write the actuarial Excel workbook (live commutation formulas, rate card, results)."""
    import sqlite3
    from pathlib import Path

    from mortality import export
    from mortality.config import PROJECT_ROOT, get_paths

    source = get_paths().database
    if not source.exists():
        source = PROJECT_ROOT / "app" / "data" / "demo.sqlite"
    con = sqlite3.connect(source)
    try:
        path = export.write_workbook(con, Path(args.out))
    finally:
        con.close()
    print(f"wrote {path} (from {source.name})")
    return 0


def cmd_app(args: argparse.Namespace) -> int:
    """Launch the dashboard."""
    import subprocess
    import sys

    from mortality.config import PROJECT_ROOT

    entry = PROJECT_ROOT / "app" / "streamlit_app.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(entry), "--server.port", str(args.port)]
    return subprocess.call(cmd)


def cmd_figures(args: argparse.Namespace) -> int:
    """Draw the README figures from the warehouse."""
    from pathlib import Path

    from mortality import figures

    for path in figures.build_all(Path(args.out)):
        print(f"  wrote {path}")
    return 0


def cmd_experience_template(args: argparse.Namespace) -> int:
    """Write a CSV template with the columns a policy extract needs."""
    from mortality import experience

    experience.write_template(args.out)
    print(f"wrote {args.out}: the extract needs these columns, one row per policy")
    return 0


def cmd_experience_generate(args: argparse.Namespace) -> int:
    """(Re)build the synthetic portfolio that the warehouse's experience study is run on."""
    from mortality import experience, warehouse
    from mortality.config import get_paths

    inputs = experience.warehouse_inputs(warehouse.connect())
    if inputs is None:
        print("The warehouse lacks the CNSF table: run `mortality db build` first.")
        return 1
    q, state_smr, weights = inputs
    portfolio = experience.load_or_generate_portfolio(
        get_paths(), q, state_smr, weights, args.force
    )
    print(
        f"{len(portfolio.policies):,} policy records, "
        f"{(portfolio.truth['true_status'] == 'DEATH').sum():,} true deaths, "
        f"{len(portfolio.defects):,} injected defects"
    )
    return 0


def cmd_experience_run(args: argparse.Namespace) -> int:
    """Run the experience study on a policy extract and write every result table as CSV."""
    from pathlib import Path

    import pandas as pd

    from mortality import experience, warehouse

    inputs = experience.warehouse_inputs(warehouse.connect())
    if inputs is None:
        print("The warehouse lacks the CNSF table: run `mortality db build` first.")
        return 1
    q, state_smr, _ = inputs
    if args.basis_csv:
        table = pd.read_csv(args.basis_csv)
        q = table.set_index("age")["qx"]
    policies = experience.load_extract(args.policies)
    print(f"{len(policies):,} records read from {args.policies}")
    results = experience.run_study(
        policies, q, state_smr, args.study_start, args.study_end, args.extract_date,
        interest=args.interest,
    )  # fmt: skip
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, frame in results.items():
        frame.to_csv(out / f"{name}.csv", index=False)
    print("\ndata validation:")
    print(results["dq_checks"].to_string(index=False))
    print("\nreconciliation:")
    print(results["dq_reconciliation"].to_string(index=False))
    total = results["ae_one_way"].query("years == 'excluding_2020_2022' and dimension == 'all'")
    if len(total):
        t = total.iloc[0]
        print(
            f"\nA/E excluding 2020-2022: {t['ae']:.3f} "
            f"(95% {t['ae_lower']:.3f} to {t['ae_upper']:.3f}), {t['deaths']:,.0f} deaths"
        )
    print(f"\nresults written to {out}")
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

    data = sub.add_parser("app-data", help="build the shareable demo bundle for the dashboard")
    data.add_argument("--out", default="app/data", help="output folder (default: app/data)")
    data.set_defaults(func=cmd_app_data)

    xl = sub.add_parser("export-excel", help="write the actuarial Excel workbook")
    xl.add_argument("--out", default="reports/Mortality_Table_Builder.xlsx")
    xl.set_defaults(func=cmd_export_excel)

    app = sub.add_parser("app", help="launch the Streamlit dashboard")
    app.add_argument("--port", type=int, default=8501)
    app.set_defaults(func=cmd_app)

    exp = sub.add_parser("experience", help="insurer-style mortality experience study")
    exp_sub = exp.add_subparsers(dest="action", required=True)
    tmpl = exp_sub.add_parser("template", help="write a CSV template of the extract columns")
    tmpl.add_argument("--out", default="policy_extract_template.csv")
    tmpl.set_defaults(func=cmd_experience_template)
    gen = exp_sub.add_parser("generate", help="rebuild the synthetic portfolio")
    gen.add_argument("--force", action="store_true", help="generate again even if cached")
    gen.set_defaults(func=cmd_experience_generate)
    run = exp_sub.add_parser("run", help="run the study on a policy extract (CSV or Parquet)")
    run.add_argument("--policies", required=True, help="the extract")
    run.add_argument("--study-start", required=True, help="first day observed, e.g. 2018-01-01")
    run.add_argument("--study-end", required=True, help="last day observed, e.g. 2024-06-30")
    run.add_argument("--extract-date", required=True, help="date the extract was taken")
    run.add_argument(
        "--basis-csv", help="expected table as CSV with columns age,qx (default CNSF 2013)"
    )
    run.add_argument("--interest", type=float, default=0.04, help="rate for the financial impact")
    run.add_argument("--out", default="data/processed/experience_study", help="output folder")
    run.set_defaults(func=cmd_experience_run)

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

    cnsf_vi = sources.add_parser(
        "cnsf-vi",
        help="CNSF individual life statistics: a folder of yearly Excel / Access downloads",
    )
    cnsf_vi.add_argument("folder", help="folder with the yearly files downloaded from the CNSF")
    cnsf_vi.add_argument("--force", action="store_true", help="parse again, ignoring the cache")
    cnsf_vi.add_argument(
        "--skip-legacy", action="store_true", help="skip the 2018 to 2020 Access databases"
    )
    cnsf_vi.set_defaults(func=cmd_ingest_cnsf_vi)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
