// Checks every LaTeX formula in the handbook, the way GitHub will read it.
//
//   node scripts/mathcheck/check.mjs [files or folders ...]     (default: docs/handbook)
//
// A formula is one of:
//   * display math between two lines that contain only "$$"
//   * one-line display math written as "$$ ... $$"
//   * inline math "$ ... $" where the opening $ is followed by a non-space, the closing $ is
//     preceded by a non-space and not followed by a digit (GitHub's rule, so "$5 and $6" is
//     not math)
// Code fences and `inline code` are skipped. Each formula is rendered with KaTeX and any parse
// error is reported with its file and line. A lone "$" that is not part of a formula is also
// an error: write money as MXN or \$ so GitHub never guesses.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import katex from "katex";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..", "..");
const targets = process.argv.slice(2).length ? process.argv.slice(2) : [path.join(root, "docs", "handbook")];

function markdownFiles(p) {
  const stat = fs.statSync(p);
  if (stat.isFile()) return p.endsWith(".md") ? [p] : [];
  return fs.readdirSync(p).flatMap((name) => markdownFiles(path.join(p, name)));
}

/** Pull the formulas out of one Markdown file. */
export function extract(text) {
  const lines = text.split("\n");
  const formulas = [];
  const problems = [];
  let fence = null;
  let block = null;
  lines.forEach((raw, i) => {
    const lineNo = i + 1;
    const line = raw.replace(/\r$/, "");
    const trimmed = line.trim();
    const fenceMatch = trimmed.match(/^(```+|~~~+)/);
    if (!block && fenceMatch) {
      fence = fence ? (trimmed.startsWith(fence[0]) ? null : fence) : fenceMatch[1];
      return;
    }
    if (fence) return;
    if (block) {
      if (trimmed === "$$") {
        formulas.push({ tex: block.lines.join("\n"), display: true, line: block.start });
        block = null;
      } else {
        block.lines.push(line);
      }
      return;
    }
    if (trimmed === "$$") {
      block = { start: lineNo, lines: [] };
      return;
    }
    // one-line display math
    const oneLine = trimmed.match(/^\$\$(.+)\$\$$/);
    if (oneLine) {
      formulas.push({ tex: oneLine[1], display: true, line: lineNo });
      return;
    }
    // inline math: remove `code` first, then scan for $...$
    const noCode = line.replace(/`[^`]*`/g, (m) => " ".repeat(m.length));
    let k = 0;
    while (k < noCode.length) {
      const ch = noCode[k];
      if (ch === "\\" && noCode[k + 1] === "$") {
        k += 2; // escaped dollar: a literal money sign
        continue;
      }
      if (ch !== "$") {
        k++;
        continue;
      }
      // find the closing $ that obeys GitHub's rule
      let end = -1;
      for (let j = k + 1; j < noCode.length; j++) {
        if (noCode[j] === "\\") {
          j++;
          continue;
        }
        if (noCode[j] === "$" && !/\s/.test(noCode[j - 1]) && !/\d/.test(noCode[j + 1] ?? "")) {
          end = j;
          break;
        }
      }
      if (end === -1 || /\s/.test(noCode[k + 1] ?? " ")) {
        problems.push({ line: lineNo, message: "a lone $ that does not open a formula (write money as MXN or \\$)" });
        k++;
        continue;
      }
      formulas.push({ tex: line.slice(k + 1, end), display: false, line: lineNo });
      k = end + 1;
    }
  });
  if (block) problems.push({ line: block.start, message: "display math opened with $$ and never closed" });
  return { formulas, problems };
}

let total = 0;
let failures = 0;
const perFile = [];
for (const file of targets.flatMap(markdownFiles)) {
  const { formulas, problems } = extract(fs.readFileSync(file, "utf8"));
  const rel = path.relative(root, file);
  let display = 0;
  for (const f of formulas) {
    total++;
    f.display ? display++ : null;
    try {
      katex.renderToString(f.tex, { displayMode: f.display, throwOnError: true, strict: "error", trust: false });
    } catch (err) {
      failures++;
      console.error(`${rel}:${f.line}: ${String(err.message).split("\n")[0]}\n    ${f.tex.slice(0, 100).replace(/\n/g, " ")}`);
    }
  }
  for (const p of problems) {
    failures++;
    console.error(`${rel}:${p.line}: ${p.message}`);
  }
  perFile.push(`${rel}: ${formulas.length} formulas (${display} display)`);
}
console.log(perFile.join("\n"));
console.log(`\n${total} formulas checked, ${failures} problem(s).`);
process.exit(failures ? 1 : 0);
