"""Crawl the built documentation site and fail on any local link, image or anchor that is dead.

MkDocs checks the Markdown it understands; this checks what a reader's browser would request,
including images written as raw HTML and the anchors the table of contents links to.

    uv run --group docs mkdocs build && uv run python scripts/check_site.py
"""

from __future__ import annotations

import posixpath
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

SITE = Path(__file__).resolve().parents[1] / "site"


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[tuple[str, str]] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "a" and a.get("name"):
            self.ids.add(a["name"])
        for key in ("href", "src"):
            if a.get(key):
                self.refs.append((tag, a[key]))


def parse(path: Path) -> Page:
    page = Page()
    page.feed(path.read_text(encoding="utf-8"))
    return page


def main() -> int:
    if not SITE.exists():
        print("no site/ folder: run `mkdocs build` first")
        return 2
    # 404.html is served from any depth, so its links are absolute to the deployed base path
    pages = {p: parse(p) for p in SITE.rglob("*.html") if p.name != "404.html"}
    problems: list[str] = []
    checked = 0
    for path, page in pages.items():
        here = "/" + path.parent.relative_to(SITE).as_posix()
        for tag, ref in page.refs:
            if re.match(r"[a-z][a-z0-9+.-]*:", ref, re.I) or ref.startswith(("//", "data:")):
                continue
            url = urlsplit(ref)
            target = unquote(url.path)
            if not target:  # a bare #anchor on this page
                dest = path
            else:
                resolved = posixpath.normpath(
                    target if target.startswith("/") else posixpath.join(here, target)
                )
                dest = SITE / resolved.lstrip("/")
                if dest.is_dir():
                    dest = dest / "index.html"
            checked += 1
            if not dest.exists():
                problems.append(f"{path.relative_to(SITE)}: <{tag}> {ref} -> missing")
            elif (
                url.fragment
                and dest.suffix == ".html"
                and dest in pages
                and unquote(url.fragment) not in pages[dest].ids
            ):
                problems.append(f"{path.relative_to(SITE)}: {ref} -> no such anchor")
    print(f"{len(pages)} pages, {checked} local references checked, {len(problems)} problems")
    for line in problems[:40]:
        print("  ", line)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
