"""Send Markdown through GitHub's own renderer and check that every formula was recognized.

    uv run python scripts/mathcheck/github_render.py docs/handbook/05-life-tables.md ...

The KaTeX checker (``check.mjs``) proves a formula *parses*. This proves GitHub will *draw* it:
GitHub reads Markdown before math, so a formula can be valid LaTeX and still be broken by
italics or tables. The script counts the formulas written in each file and the ``math-renderer``
elements GitHub returns, and fails when they differ or a stray ``$`` survives in the text.

It calls the public ``POST /markdown`` endpoint (about 60 requests an hour without a token),
so run it on the files you changed, not on the whole repository.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parents[2]
REPO = "deadmigue55/Mortality-Table-Builder"


def expected_formulas(text: str) -> int:
    """Formulas written in a file: $`...`$ inline, $$ ... $$ blocks, one-line $$...$$."""
    count, fenced, block = 0, False, False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            fenced = not fenced
        if fenced:
            continue
        if stripped == "$$":
            if block:
                count += 1
            block = not block
            continue
        if block:
            continue
        if re.fullmatch(r"\$\$.+\$\$", stripped):
            count += 1
            continue
        shown = re.sub(r"(`{2,}).+?\1", " ", line)  # a code span may show the syntax: not a formula
        count += len(re.findall(r"(?<![\w$`])\$`[^`]+`\$", shown))
    return count


def render(text: str) -> str:
    request = urllib.request.Request(
        "https://api.github.com/markdown",
        data=json.dumps({"text": text, "mode": "gfm", "context": REPO}).encode(),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "mortality-table-builder-check",
            "Accept": "application/vnd.github+json",
        },
    )
    return urllib.request.urlopen(request, timeout=60).read().decode("utf-8")


def check(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    html = render(text)
    drawn = len(re.findall(r"<math-renderer", html))
    visible = re.sub(r"<(code|pre)[^>]*>.*?</\1>", " ", html, flags=re.S)
    visible = re.sub(r"<math-renderer.*?</math-renderer>", " ", visible, flags=re.S)
    stray = len(re.findall(r"\$", re.sub(r"<[^>]+>", " ", visible)))
    want = expected_formulas(text)
    ok = drawn == want and stray == 0
    status = "ok  " if ok else "FAIL"
    print(f"{status} {path.relative_to(ROOT)}: {drawn} drawn of {want} written, {stray} stray $")
    return ok


def main(argv: list[str]) -> int:
    files = [Path(a).resolve() for a in argv] or sorted((ROOT / "docs" / "handbook").glob("*.md"))
    results = [check(f) for f in files]
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
