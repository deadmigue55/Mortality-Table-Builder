# The handbook

**The mathematics behind every number in this project, explained from the ground up.**

The [front page](../../README.md) and the [results](../results.md) say *what was found*, in plain words. This handbook says *how, and why you can believe it*: each method is derived step by step in LaTeX, checked against a worked example small enough to do by hand, and tied to the function that implements it and the test that proves the two agree.

> [!TIP]
> **How to read it.** New to actuarial work? Start with the [glossary](00-glossary.md), then the [notation](01-notation.md), then chapter 5, which is a complete small theory in itself. Already an actuary? Go straight to the chapter you want: every chapter opens with a one-minute summary, so you can see in a minute whether it holds what you need.

## The chapters

| # | Chapter | The question it answers | Results (plain words) | Code | Status |
|:-:|---|---|---|---|:-:|
| | [Glossary](00-glossary.md) | What does each term mean? | | | done |
| 1 | [Notation and conventions](01-notation.md) | What does each symbol mean, once and for all? | | | done |
| 2 | Data, exposure and quality | How do records become exposure and rates? | [Data quality](../data-quality.md), [warehouse](../warehouse.md) | `quality.py`, `lexis.py` | in progress |
| 3 | Crude rates and comparison | How big is the gap, and how sure are we? | [Crude rates](../crude-rates.md) | `rates.py` | in progress |
| 4 | Graduation | How do we smooth rates without losing the truth? | [Graduation](../graduation.md) | `graduation.py` | in progress |
| 5 | [Life tables and actuarial functions](05-life-tables.md) | How does a rate become a price? | [Life tables](../life-tables.md) | `lifetable.py` | done |
| 6 | Projection | How will mortality change? | [Projection](../projection.md) | `projection.py` | in progress |
| 7 | Experience study | How does a company's own experience compare, and how sure is it? | [Experience study](../experience-study.md) | `experience.py` | in progress |
| 8 | Pricing, profit and reserves | What should a policy cost? | [Pricing](../pricing.md) | `pricing.py` | in progress |
| 9 | Excess mortality and stress tests | What did the pandemic cost, and what would a repeat do? | [Excess](../excess-mortality.md), [stress](../stress-tests.md) | `excess.py`, `stress.py` | in progress |
| 10 | Reinsurance | How is risk shared and priced? | [Reinsurance](../reinsurance.md) | `reinsurance.py` | in progress |
| 11 | The insured-lives table | Which table should a quote use? | [Insured lives](../insured-lives.md) | `insured*.py` | in progress |

## What every chapter contains

| Block | What it gives you |
|---|---|
| **In one minute** | The idea in plain words, and the one number worth remembering |
| **Definitions and derivations** | Each formula derived from the one before it, numbered so it can be cited |
| **A worked example** | A table small enough to check by hand, with its numbers locked by a test |
| **Validation** | The independent checks the method passes: a closed-form case, another dataset, another language |
| **Code map** | For each formula, the function that implements it and the test that checks it |
| **Limits** | What the method assumes and where it stops being right |

## How the handbook stays correct

A mathematical document that nobody can check rots. Three safeguards keep this one honest, and they run on every change:

1. **Every formula is tested against the code.** `tests/test_handbook_*.py` evaluates the identities of a chapter numerically (for example $`A_x = 1 - d\,\ddot{a}_x`$ at every age, or prospective equals retrospective reserve) and fails if the software and the text disagree. While writing chapter 5 this caught a sentence that overstated what the code returns above the oldest age; the text and the docstring were corrected.
2. **Every formula is syntax-checked.** `node scripts/mathcheck/check.mjs` renders each LaTeX expression with KaTeX and rejects any that does not parse.
3. **Every formula is drawn by GitHub.** Valid LaTeX can still be broken by Markdown: GitHub reads italics before math. `scripts/mathcheck/github_render.py` sends each chapter through GitHub's own renderer and counts the formulas it draws against the formulas written. It caught 6 broken formulas in chapter 5 that the syntax check could not see, which is why inline math is written with a backtick inside the dollars.
4. **Every number comes from the data.** Results quoted in the chapters are the ones the pipeline produces, and a worked example's numbers are asserted in a test, so a changed method cannot leave a stale figure behind.

## References

Each chapter lists its sources. The main textbooks are Bowers et al., *Actuarial Mathematics* (Society of Actuaries); Dickson, Hardy and Waters, *Actuarial Mathematics for Life Contingent Risks* (Cambridge); Preston, Heuveline and Guillot, *Demography* (Blackwell); and the *Methods Protocol* of the Human Mortality Database.
