// MathJax for the handbook: the Markdown carries \( ... \) and $$ ... $$ (see scripts/docs_hooks.py).
window.MathJax = {
  loader: { load: ["[tex]/boldsymbol", "[tex]/cancel", "[tex]/color"] },
  tex: {
    packages: { "[+]": ["boldsymbol", "cancel", "color"] },
    inlineMath: [["\\(", "\\)"]],
    displayMath: [["\\[", "\\]"]],
    processEscapes: true,
    processEnvironments: true,
    tags: "none",
  },
  options: {
    ignoreHtmlClass: ".*|",
    processHtmlClass: "arithmatex",
  },
};

// Material swaps pages without reloading: typeset the new page's formulas each time.
document$.subscribe(() => {
  if (window.MathJax && MathJax.startup && MathJax.typesetPromise) {
    MathJax.startup.output.clearCache();
    MathJax.typesetClear();
    MathJax.texReset();
    MathJax.typesetPromise();
  }
});
