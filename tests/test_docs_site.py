"""The documentation site is built from the same Markdown GitHub shows, through a few transforms.

These tests pin the transforms (so a change to one cannot silently break a page) and check that
every page is in the site menu. The build itself, and the crawl of its links, run in the docs
workflow, which has the documentation tools; nothing here needs them.
"""

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("docs_hooks", ROOT / "scripts" / "docs_hooks.py")
hooks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hooks)

MARKDOWN = sorted((ROOT / "docs").rglob("*.md"))


def test_inline_math_written_for_github_becomes_mathjax():
    text = (
        "so $`\\hat\\mu_x = D_x / E_x`$ and $`q_x`$ hold; `$` is untouched, and so is $$ block $$."
    )
    out = hooks.INLINE_MATH.sub(lambda m: "\\(" + m.group(1) + "\\)", text)
    assert "\\(\\hat\\mu_x = D_x / E_x\\)" in out and "\\(q_x\\)" in out
    assert "`$` is untouched" in out and "$$ block $$" in out


def test_a_github_callout_becomes_an_admonition():
    source = "Intro.\n> [!NOTE]\n> **In one minute.** First line,\n>\n> second paragraph.\n\nAfter."
    out = hooks._callouts(source)
    assert (
        out
        == 'Intro.\n\n!!! note ""\n    **In one minute.** First line,\n\n    second paragraph.\n\n\nAfter.'
    )
    assert hooks._callouts("> [!IMPORTANT]\n> x").startswith('!!! info ""\n    x')
    assert hooks._callouts("a plain\n> quote\n") == "a plain\n> quote\n"


def test_every_callout_in_the_pages_is_one_the_hook_understands():
    for path in [ROOT / "README.md", *MARKDOWN]:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"^>\s*\[!", line):
                assert hooks.ALERT.match(line), f"{path.name}:{number}: {line}"


@pytest.mark.parametrize(
    ("src_uri", "link", "expected"),
    [
        ("results.md", "../README.md", "index.md"),
        ("handbook/04-graduation.md", "../../README.md", "../index.md"),
        (
            "results.md",
            "../reports/methodology.pdf",
            f"{hooks.REPO}/blob/main/reports/methodology.pdf",
        ),
        ("results.md", "handbook/README.md", "handbook/README.md"),  # inside docs: left to MkDocs
        ("results.md", "https://example.org/x.pdf", "https://example.org/x.pdf"),
    ],
)
def test_links_that_leave_the_docs_folder_are_pointed_somewhere_that_exists(
    src_uri, link, expected
):
    assert hooks._page_links(f"[x]({link})", src_uri) == f"[x]({expected})"


def test_readme_links_are_made_relative_to_the_docs_folder():
    text = '[a](docs/results.md) [b](reports/methodology.pdf) [c](https://x.org) <img src="docs/img/a.png">'
    out = hooks._readme_links(text)
    assert "[a](results.md)" in out and 'src="img/a.png"' in out and "[c](https://x.org)" in out
    assert f"[b]({hooks.REPO}/blob/main/reports/methodology.pdf)" in out


@pytest.mark.parametrize(
    ("src_uri", "src", "expected"),
    [
        ("index.md", "img/a.png", "img/a.png"),
        ("results.md", "img/a.png", "../img/a.png"),  # published at results/, one level down
        ("handbook/README.md", "../img/a.png", "../img/a.png"),  # published at handbook/
        ("handbook/04-graduation.md", "../img/a.png", "../../img/a.png"),
    ],
)
def test_images_written_as_raw_html_find_their_file_from_the_published_page(src_uri, src, expected):
    assert hooks._html_assets(f'<img src="{src}">', src_uri) == f'<img src="{expected}">'


def test_every_page_in_docs_is_in_the_site_menu():
    """A page that is not in the menu is published but unreachable: easy to forget for a new chapter."""
    config = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    listed = set(re.findall(r":\s+([\w./-]+\.md)\s*$", config, re.M))
    on_disk = {p.relative_to(ROOT / "docs").as_posix() for p in MARKDOWN}
    assert on_disk - listed == set(), "pages missing from the nav of mkdocs.yml"
    assert listed - on_disk - {"index.md"} == set(), "nav entries with no file"


def test_the_mathjax_setup_loads_every_extension_the_handbook_uses():
    """\\boldsymbol, \\cancel and \\color are not in MathJax's default bundle (a formula using one
    shows as red text), so each must be loaded whenever a chapter uses it."""
    script = (ROOT / "docs" / "javascripts" / "mathjax.js").read_text(encoding="utf-8")
    used = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "docs" / "handbook").glob("*.md"))
    for command, package in (
        ("boldsymbol", "boldsymbol"),
        ("cancel", "cancel"),
        ("color", "color"),
    ):
        if re.search(rf"\\{command}\b", used):
            assert f'"{package}"' in script, (
                f"\\{command} is used but the {package} package is not loaded"
            )
