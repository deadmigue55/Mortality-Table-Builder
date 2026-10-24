# Design research: what makes a top project README work

Notes behind the 2026 restructuring of this repository's front page. The goal was a README that a hiring manager can
read in 60 seconds and a specialist can trust, with the depth one click away.

## What was studied

| Repository | Why it was chosen | What it does well |
|---|---|---|
| [astral-sh/uv](https://github.com/astral-sh/uv) | One of the most-starred Python tools; its README is short | About 150 lines; a one-line tagline; three badges; a light/dark benchmark chart; a bulleted list of highlights; real terminal transcripts; everything else links to a docs site |
| [rasbt/LLMs-from-scratch](https://github.com/rasbt/LLMs-from-scratch) | A teaching repository with a huge audience | A chapter table with "quick" and "full" links; a diagram of the mental model; progressive disclosure; a citation block |
| [pola-rs/polars](https://github.com/pola-rs/polars) | A data library with a polished front page | A banner, a badge row, a navigation strip, bold keywords in the feature list, code before prose |

## What they have in common

1. **Results before process.** The first screen says what it does and shows evidence (a chart, a benchmark, a transcript).
   Explanations of how it works come after the reader is interested.
2. **A short front page that links outward.** None of them tries to document everything in the README. Depth lives in
   docs the README points to.
3. **Scannable structure.** A tagline, a handful of badges, a table or a bulleted list, then code or a figure.
4. **Evidence you can check.** Benchmarks, outputs and numbers are real and reproducible.
5. **Honesty about scope.** The good ones say what they do not do.

## What we took

| Pattern | Where it appears here |
|---|---|
| One-sentence tagline and a hero image | The top of the [README](../README.md): the social card with the headline numbers |
| A "short version" in plain words | README, first section, written without jargon, with actuarial terms kept and glossed |
| A results table up front | "Results at a glance": every number verified against the shipped database |
| Chapter-style table with quick and full links | "Pick your path" and the pipeline table, which link to the results page and the handbook chapter for each step |
| Progressive disclosure | The README stays near 200 lines; per-step results moved to [results.md](results.md) and the mathematics to the [handbook](handbook/README.md) |
| Honesty section | "What it does not claim" |
| Trust signals | "How we know it is right": the check counts, the independent R cross-check, the tests that tie each formula to the code |

## How the claims are protected

A README that promises numbers is only as good as its upkeep, so the numbers are tested, not trusted:

- `tests/test_docs_integrity.py` fails if a relative link or anchor breaks, if the check count or the page count in the
  README drifts from the code, if British spellings creep in, or if a chapter marked "done" has no file.
- The handbook's formulas are checked three ways (see [the handbook index](handbook/README.md)): a KaTeX syntax check,
  numeric tests against the code, and a render through GitHub's own Markdown renderer.
- About 35 headline figures in the README were re-derived from `app/data/demo.sqlite` on the day of the restructuring.

## Lessons worth keeping

- GitHub's Markdown turns underscores inside plain dollar-delimited math into italics, which silently broke 6 of 242
  formulas. Inline math is therefore written with a backtick just inside each dollar sign (as the handbook's formulas
  show), and the checker rejects the plain form.
- A figure can go stale without anyone editing it: the pipeline diagram said "100 data checks" and "9 pages" after the
  project had 122 and 10. It now reads both numbers from the code.
- The "3 million death records" figure was wrong (the INEGI microdata hold 4,676,249 registered deaths for 2020 to 2024),
  and it had been copied into the dashboard, the social card, the README and the portfolio. One number, one source.

## The documentation site

uv, polars and most of the repositories studied send readers who want depth to a documentation site, so this one has
one: <https://deadmigue55.github.io/Mortality-Table-Builder/> (MkDocs Material, MathJax, search, light and dark).

- **One source.** The site is built from the same Markdown GitHub shows; the README is its front page. A small hook
  (`scripts/docs_hooks.py`) converts what only GitHub understands while the site is built: the inline math written
  `` $`...`$ `` becomes `\(...\)`, `> [!NOTE]` callouts become admonitions, and links that leave `docs/` point at the
  repository. Nothing is duplicated, so the repository and the site cannot drift apart.
- **Checked like the rest.** Every push builds the site in strict mode, then `scripts/check_site.py` crawls the result
  (about 2,800 links, images and anchors) and fails on a dead one; `tests/test_docs_site.py` pins the transforms and
  fails if a page is missing from the menu. A browser check, run by hand when the math setup changes
  (it needs a real browser, so it is not in the workflow), typesets every chapter in MathJax, compares the formulas
  drawn with the formulas written, and looks for any that show an unknown command.
- **Two things only the site could show.** MathJax's default bundle lacks `\boldsymbol` and `\cancel`: a formula
  that uses one shows as red text until the extension is loaded, which no Markdown check can see. And an image
  written as raw HTML (`<img src>`) in a page that is not at the site root pointed one folder too shallow and returned
  404; MkDocs only fixes Markdown-style images. Both are now handled and tested.

## Not done (yet)

- A dark-mode variant of the hero image through a `<picture>` element.
