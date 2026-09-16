# mermaid-diagram-tool

Render Mermaid diagrams to SVG and PDF with a consistent house style, and
verify that the result is readable before shipping it.

## Install

```bash
npm install -g @mermaid-js/mermaid-cli   # provides mmdc
brew install imagemagick                 # only for mermaid2pdf
```

Clone this repo to `~/.mermaid` and source the functions from your shell rc:

```bash
export MERMAID_HOME="$HOME/.mermaid"
source "$MERMAID_HOME/mermaid2svg.sh"
source "$MERMAID_HOME/mermaid2pdf.sh"
```

## Usage

```bash
mermaid2svg diagram.mermaid                     # default grayscale theme
mermaid2svg diagram.mermaid --style flow        # business process-map theme
mermaid2svg doc.md --style flow --check         # render every block, then verify
mermaid-check.py diagram.svg -v                 # verify only, list crossing pairs

mermaid2pdf diagram.mermaid                     # PDF with title header and logo
mermaid2pdf diagram.mermaid --simple            # logo overlay only
mermaid2pdf diagram.mermaid --nologo --png      # plain PNG
```

A Markdown input with N diagrams writes `<input>-1.svg` through `<input>-N.svg`.
The `-o` path is ignored for Markdown.

The PDF title comes from a `%% Title: ...` comment on the first line of the
`.mermaid` file, falling back to the file name.

## Files

| File | Role |
|---|---|
| `mermaid2svg.sh` | shell function: render, `--style <name>`, `--check` |
| `mermaid2pdf.sh` | shell function: render to PNG, add header and logo, convert to PDF |
| `mermaid-check.py` | geometry checker run by `--check`; importable as a module |
| `mermaid-config.json`, `mermaid-styles.css` | default grayscale theme, HTML labels |
| `mermaid-config-flow.json`, `mermaid-styles-flow.css` | flow theme: navy and red, SVG text labels |
| `planvital-logo.png` | header asset for `mermaid2pdf` |

A style named `foo` resolves to `mermaid-config-foo.json` and
`mermaid-styles-foo.css`; either file may be absent. A `mermaid-config.json` in
the current directory overrides the selected config.

## What the checker reports

`mermaid-check.py` parses the rendered SVG and exits non-zero on four defects:

- an edge label sitting on a node
- two edge labels sitting on each other
- an edge passing through a node it does not connect
- an edge label sitting on an edge that is not its own

Edge crossings are counted and reported but never fail the check, since some
are structural. Use the count to compare declaration orderings objectively.

Inspect renders with `mmdc` to PNG. Do not judge output with `rsvg-convert`:
it drops `foreignObject` labels and mangles `tspan` spacing.

## Authoring rules for the flow style

The header comment of `mermaid-styles-flow.css` is the canonical rule list.
The two that cause the most damage:

1. Write dotted labelled edges as `A -.->|texto| B`, never `A -.texto.-> B`.
   The second form silently drops the last character of the label in the SVG.
2. Every edge leaving a diamond must answer that diamond's question. A third
   outcome on a yes/no question is a second condition that needs its own node.

Work top-down and stop at the first layer that fixes a problem: agree the
as-is, keep one chart, fix the model, render and check, read the checker as a
modelling report, then search declaration order, then connectors, legend last.
Never tune `nodeSpacing`, `padding` or aspect ratio before the last two steps.
