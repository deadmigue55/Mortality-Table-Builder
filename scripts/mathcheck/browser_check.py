"""Typeset every handbook chapter of the built site in a real browser and look for broken math.

The KaTeX check and GitHub's renderer test the formulas as GitHub shows them; this tests them as
the documentation site shows them, with MathJax. It fails if a formula is not drawn, is drawn
twice, or shows an unknown command (MathJax draws one as red text without raising an error).

It needs a browser, so it is run by hand when the math setup changes, not in the workflow:

    uv run --group docs mkdocs build
    uv run --no-project --with playwright python -I scripts/mathcheck/browser_check.py
"""

from __future__ import annotations

import functools
import http.server
import socketserver
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

SITE = Path(__file__).resolve().parents[2] / "site"

# Per formula: drawn exactly once, no parse error, no leftover backslash command in the output.
PROBE = r"""() => {
  const spans = [...document.querySelectorAll('.arithmatex')];
  const problems = [];
  for (const s of spans) {
    const drawn = s.querySelectorAll('mjx-container');
    const text = drawn[0] ? drawn[0].textContent.replace(/\s/g, '') : '';
    const label = s.textContent.slice(0, 50);
    if (drawn.length !== 1) problems.push('drawn ' + drawn.length + ' times: ' + label);
    else if (s.querySelector('mjx-merror') || /\\[A-Za-z]{2,}/.test(text))
      problems.push('error: ' + label);
  }
  const callout = /\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]/g;
  const rawCallouts = (document.body.innerText.match(callout) || []).length;
  return {formulas: spans.length, problems, rawCallouts};
}"""


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main() -> int:
    pages = sorted(
        p.parent.relative_to(SITE).as_posix() for p in SITE.glob("handbook/*/index.html")
    )
    server = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(SITE)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/"
    failed = total = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for path in pages:
            page.goto(base + path + "/", wait_until="load")
            page.wait_for_function("window.MathJax && MathJax.startup && MathJax.startup.promise")
            page.evaluate("MathJax.startup.promise")
            page.wait_for_timeout(300)
            result = page.evaluate(PROBE)
            total += result["formulas"]
            bad = result["problems"] + (
                ["a callout is shown as text"] if result["rawCallouts"] else []
            )
            failed += len(bad)
            print(f"{path:40s} {result['formulas']:4d} formulas  {'ok' if not bad else bad[:3]}")
        browser.close()
    server.shutdown()
    print(f"{total} formulas on {len(pages)} pages, {failed} problems")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
