"""MkDocs hooks that let one set of Markdown files serve GitHub and the documentation site.

The pages are written for GitHub, which has two quirks the site does not share:

* inline math is written ``$`...`$`` (a backtick just inside each dollar sign, so GitHub does not
  read underscores as italics); the site wants ``\\(...\\)``, which MathJax understands;
* callouts are written ``> [!NOTE]``; the site draws them as admonitions;
* the repository README is the front page, and it sits outside ``docs/``, so its links begin with
  ``docs/`` and some of them point at files the site does not publish (the PDF report, the Excel
  workbook, the license), which go to the copy on GitHub.

Nothing is copied or edited on disk: the same text is transformed while the site is built, so the
repository and the site cannot drift apart.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

REPO = "https://github.com/deadmigue55/Mortality-Table-Builder"
README = Path(__file__).resolve().parents[1] / "README.md"

# $`x_t`$ -> \(x_t\)
INLINE_MATH = re.compile(r"\$`([^`\n]+?)`\$")
ALERT = re.compile(r"^> \[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$")
ADMONITION = {
    "NOTE": "note",
    "TIP": "tip",
    "IMPORTANT": "info",
    "WARNING": "warning",
    "CAUTION": "danger",
}
# the target of a Markdown link, or of an HTML src / href
TARGET = re.compile(r"(\]\(|\bsrc=\"|\bhref=\")([^)\"\s#]+)")


def _is_local(target: str) -> bool:
    return not re.match(r"[a-z][a-z0-9+.-]*:", target, re.I) and not target.startswith(("/", "#"))


def _github(path: str) -> str:
    return f"{REPO}/blob/main/{path}"


def _readme_links(text: str) -> str:
    """README links, written relative to the repository root, made relative to the docs folder."""

    def fix(match: re.Match) -> str:
        head, target = match.groups()
        if not _is_local(target):
            return match.group(0)
        if target.startswith("docs/"):
            return head + target.removeprefix("docs/")
        return head + _github(target)  # reports/, LICENSE, CITATION.cff: not part of the site

    return TARGET.sub(fix, text)


def _page_links(text: str, src_uri: str) -> str:
    """Links that climb out of docs/ (to the README, the PDF report...) made to work on the site."""
    here = posixpath.dirname(src_uri)

    def fix(match: re.Match) -> str:
        head, target = match.groups()
        if not _is_local(target):
            return match.group(0)
        resolved = posixpath.normpath(posixpath.join(here, target))
        if not resolved.startswith(".."):
            return match.group(0)
        outside = resolved.removeprefix("../")
        if outside == "README.md":
            return head + posixpath.relpath("index.md", here or ".")
        return head + _github(outside)

    return TARGET.sub(fix, text)


HTML_ASSET = re.compile(r"(\bsrc=\")([^\"\s#]+)")


def _html_assets(text: str, src_uri: str) -> str:
    """``<img src>`` written in raw HTML: MkDocs fixes Markdown images but not these, and a page
    is published at ``results/`` (not ``results.md``), so the path needs one more step up."""
    here = posixpath.dirname(src_uri)
    published = here if posixpath.basename(src_uri) in {"index.md", "README.md"} else src_uri[:-3]

    def fix(match: re.Match) -> str:
        head, target = match.groups()
        if not _is_local(target):
            return match.group(0)
        resolved = posixpath.normpath(posixpath.join(here, target))
        return head + posixpath.relpath(resolved, published or ".")

    return HTML_ASSET.sub(fix, text)


def _callouts(text: str) -> str:
    """GitHub's ``> [!NOTE]`` block quotes as Material admonitions (``!!! note``)."""
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        alert = ALERT.match(lines[i])
        if not alert:
            out.append(lines[i])
            i += 1
            continue
        if out and out[-1].strip():
            out.append("")
        out.append(f'!!! {ADMONITION[alert.group(1)]} ""')
        i += 1
        while i < len(lines) and lines[i].startswith(">"):
            body = lines[i][1:].removeprefix(" ")
            out.append("    " + body if body.strip() else "")
            i += 1
        out.append("")
    return "\n".join(out)


def on_files(files, config):
    """Publish the repository README as the home page."""
    from mkdocs.structure.files import File  # only the build has MkDocs; the tests do not

    text = _readme_links(README.read_text(encoding="utf-8"))
    # GitHub renders Markdown inside these blocks; the site has to be told to
    text = text.replace('<div align="center">', '<div align="center" markdown="1">')
    text = text.replace("<details>", '<details markdown="1">')
    text = (
        "---\nhide:\n  - navigation\n---\n\n"
        '<h1 class="sr-only">Mortality Table Builder</h1>\n\n' + text
    )
    files.append(File.generated(config, "index.md", content=text))
    return files


def on_page_markdown(markdown, page, config, files):
    if page.file.src_uri != "index.md":
        markdown = _page_links(markdown, page.file.src_uri)
    markdown = _html_assets(markdown, page.file.src_uri)
    markdown = INLINE_MATH.sub(lambda m: "\\(" + m.group(1) + "\\)", markdown)
    return _callouts(markdown)
