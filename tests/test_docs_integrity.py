"""The documentation must not rot: every link resolves and every quoted count is the real one.

These checks exist because a README is read before any code is, so a dead link or a stale number
there costs more than a bug in a helper. They run on every commit with the rest of the suite.
"""

import re
from pathlib import Path

import pytest

from mortality.validate import N_CHECKS

ROOT = Path(__file__).parents[1]
MARKDOWN = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
LINK = re.compile(
    r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|<img[^>]+src=\"([^\"]+)\"|<a[^>]+href=\"([^\"]+)\""
)


def headings(path: Path) -> set[str]:
    """GitHub's anchor for each heading: lower case, punctuation dropped, spaces to hyphens."""
    seen: dict[str, int] = {}
    slugs: set[str] = set()
    fenced = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
        match = None if fenced else re.match(r"^(#{1,6})\s+(.*?)\s*#*$", line)
        if not match:
            continue
        text = re.sub(
            r"<[^>]+>|`|\*|\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1) or "", match.group(2)
        )
        slug = re.sub(r"[^\w\- ]", "", text.lower()).strip().replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        slugs.add(slug if count == 0 else f"{slug}-{count}")
    return slugs


def relative_links(path: Path):
    fenced = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip().startswith("```"):
            fenced = not fenced
        if fenced:
            continue
        for match in LINK.finditer(re.sub(r"`[^`]*`", "", line)):
            target = next(group for group in match.groups() if group)
            if not target.startswith(("http://", "https://", "mailto:")):
                yield number, target


@pytest.mark.parametrize("path", MARKDOWN, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_relative_link_image_and_anchor_resolves(path):
    problems = []
    for number, target in relative_links(path):
        name, _, fragment = target.partition("#")
        destination = (path.parent / name).resolve() if name else path.resolve()
        if name and not destination.exists():
            problems.append(f"line {number}: missing file {target}")
        elif (
            fragment
            and destination.suffix == ".md"
            and fragment.lower() not in headings(destination)
        ):
            problems.append(f"line {number}: no heading #{fragment} in {destination.name}")
    assert not problems, "\n".join(problems)


def test_the_readme_quotes_the_real_number_of_data_checks():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"{N_CHECKS} data checks" in readme
    assert f"data%20checks-{N_CHECKS}" in readme  # the badge


def test_the_readme_quotes_the_real_number_of_dashboard_pages():
    pages = len([p for p in (ROOT / "app" / "views").glob("*.py") if p.name != "__init__.py"])
    words = {10: "ten pages", 9: "nine pages", 11: "eleven pages", 12: "twelve pages"}
    assert words.get(pages, f"{pages} pages") in (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_pipeline_diagram_reads_its_counts_from_the_code():
    source = (ROOT / "src" / "mortality" / "figures.py").read_text(encoding="utf-8")
    assert "N_CHECKS" in source and "n_pages" in source
    assert "100 data checks" not in source and "9 pages" not in source


def test_a_chapter_marked_done_in_the_handbook_index_exists():
    index = (ROOT / "docs" / "handbook" / "README.md").read_text(encoding="utf-8")
    for row in index.splitlines():
        if row.startswith("|") and row.rstrip().endswith("| done |"):
            link = re.search(r"\]\(([^)#]+\.md)\)", row)
            assert link, f"a chapter marked done has no link: {row[:60]}"
            assert (ROOT / "docs" / "handbook" / link.group(1)).exists()


def test_documentation_uses_american_spelling():
    """One spelling throughout; code spans (`standardised_trend`) and reference lists, where
    titles keep the spelling they were published with, are skipped."""
    british = re.compile(
        r"\b(standardis\w+|modelling|modelled|labelled|summaris\w+|penalis\w+|optimis(?:e|ed|er|ing)\b"
        r"|judgement|behaviour\w*|ageing|centres?|colour\w*|licence)\b",
        re.I,
    )
    offenders = []
    for path in MARKDOWN:
        fenced = in_references = False
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("```"):
                fenced = not fenced
            if fenced:
                continue
            if line.startswith("#"):
                in_references = line.strip().lower() == "## references"
            if in_references:
                continue
            plain = re.sub(r"`[^`]*`|\]\([^)]*\)|https?://\S+", " ", line)
            offenders += [f"{path.name}:{number}: {m.group(0)}" for m in british.finditer(plain)]
    assert not offenders, "\n".join(offenders[:20])


BRITISH_WORDS = re.compile(
    r"\b(standardis\w+|modell\w*|labell\w*|summaris\w+|penalis\w+|optimis(?:e|ed|es|er|ing|ation)"
    r"|judgement|behaviour\w*|ageing|centres?|colour\w*|licence|favour\w*|subsidis\w+|grey"
    r"|analyse\w*|normalis\w+|recognis\w+|utilis\w+|organis\w+|characteris\w+|minimis\w+"
    r"|maximis\w+|realis(?:e|ed|es|ing|ation)|programme|catalogue|whilst)\b",
    re.I,
)


def test_text_shown_to_readers_by_the_figures_and_the_dashboard_is_american():
    """The pages are checked above; the words drawn on a chart or typed in the dashboard are
    string literals in the code, so read those too (identifiers and SQL names are not text)."""
    import ast

    files = [
        *sorted((ROOT / "src" / "mortality").rglob("*.py")),
        *sorted((ROOT / "app").rglob("*.py")),
    ]
    offenders = []
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if re.fullmatch(r"[a-z0-9_.]+", node.value):  # a file or table name, not text
                    continue
                for m in BRITISH_WORDS.finditer(node.value):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}: {m.group(0)}")
    assert not offenders, "\n".join(offenders[:30])
