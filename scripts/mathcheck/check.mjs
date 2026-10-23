// Checks every LaTeX formula in the handbook, the way GitHub will read it.
//
//   node scripts/mathcheck/check.mjs [files or folders ...]     (default: docs/handbook)
//
// A formula is one of:
//   * display math between two lines that contain only "$$"
//   * one-line display math written as "$$ ... $$"
//   * inline math written as $`...`$ (a dollar, a backtick, the formula, a backtick, a dollar)
//
// Inline math MUST use the backtick form. GitHub's Markdown parser reads the underscores of a
// plain $...$ formula as italics before it looks for math, so formulas such as
// ${}_nq_x$ or $(1-\phi_x)\,\mathring{e}_x$ are silently broken (found by sending the handbook
// through GitHub's own renderer: 6 of 242 formulas failed in plain form, 0 in backtick form).
// A plain $...$ pair is therefore an error here, as is a lone "$".
//
// Code fences and `inline code` are skipped. Each formula is rendered with KaTeX and any parse
// error is reported with its file and line. Write money as MXN or \$.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import katex from "katex";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..", "..");
const args = process.argv.slice(2);
const targets = args.length ? args : [path.join(root, "docs", "handbook")];

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
  let closedAt = -1;
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
        closedAt = lineNo;
      } else {
        block.lines.push(line);
      }
      return;
    }
    // GitHub only reads a display block that is a paragraph of its own: a blank line before the
    // opening $$ and after the closing $$ (found when one such block was drawn as plain text)
    if (closedAt === lineNo - 1 && trimmed !== "") {
      problems.push({ line: lineNo, message: "write a blank line after the closing $$ of a display formula" });
    }
    if (trimmed === "$$") {
      if (i > 0 && lines[i - 1].trim() !== "") {
        problems.push({ line: lineNo, message: "write a blank line before the opening $$ of a display formula" });
      }
      block = { start: lineNo, lines: [] };
      return;
    }
    const oneLine = trimmed.match(/^\$\$(.+)\$\$$/);
    if (oneLine) {
      formulas.push({ tex: oneLine[1], display: true, line: lineNo });
      return;
    }
    // 0) a code span written with two or more backticks may *show* the formula syntax: skip it
    const shown = line.replace(/(`{2,}).+?\1/g, (m) => " ".repeat(m.length));
    // 1) the allowed inline form: $`...`$ (the opening $ never follows another $, a backtick or a word)
    let rest = shown.replace(/(?<![\w$`])\$`([^`]+)`\$/g, (_, tex) => {
      formulas.push({ tex, display: false, line: lineNo });
      return " ".repeat(tex.length + 4);
    });
    // 2) mask ordinary `code` spans and escaped dollars, then anything left with a $ is a problem
    rest = rest.replace(/`[^`]*`/g, (m) => " ".repeat(m.length)).replace(/\\\$/g, "  ");
    if (rest.includes("$")) {
      const plain = /\$[^\s$][^$]*[^\s$]\$|\$[^\s$]\$/.test(rest);
      problems.push({
        line: lineNo,
        message: plain
          ? "plain $...$ inline math is fragile on GitHub: write it as $`...`$"
          : "a lone $ that does not open a formula (write money as MXN or \\$)",
      });
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
    if (f.display) display++;
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
