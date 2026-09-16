#!/bin/bash
# ===========================================
# Mermaid to SVG Converter
# ===========================================
# Usage: mermaid2svg <input.mermaid> [output.svg] [--style <name>] [--check]
#
# Examples:
#   mermaid2svg diagram.mermaid
#   mermaid2svg diagram.mermaid custom-name.svg
#   mermaid2svg diagram.mermaid --style flow
#   mermaid2svg diagram.mermaid out.svg -s flow
#   mermaid2svg diagram.md --style flow --check
#
# --check runs mermaid-check.py over the generated SVG and reports labels that
# collide with nodes, with each other, or that sit on an edge they do not
# belong to. Non-zero exit when something collides.
#
# --style <name> selects an alternative theme, resolved as
#   $MERMAID_HOME/mermaid-config-<name>.json
#   $MERMAID_HOME/mermaid-styles-<name>.css
# Either file may be absent; the default is used for whichever
# one is missing. With no --style, behaviour is unchanged.
#
# Available styles:
#   (default)  grayscale, curved edges, HTML labels
#   flow       business process map: navy/red, curved edges,
#              SVG text labels (portable outside a browser)
# ===========================================

MERMAID_HOME="${MERMAID_HOME:-$HOME/.mermaid}"

mermaid2svg() {
  local input=""
  local output=""
  local style=""
  local do_check=0

  # Parse args: --style/-s anywhere, positionals in order
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --check)
        do_check=1
        shift
        ;;
      --style|-s)
        style="$2"
        if [[ -z "$style" ]]; then
          echo "Error: --style requires a name (e.g. --style flow)"
          return 1
        fi
        shift 2
        ;;
      --style=*)
        style="${1#*=}"
        shift
        ;;
      -h|--help)
        echo "Usage: mermaid2svg <input.mermaid> [output.svg] [--style <name>] [--check]"
        echo "Styles: default, flow"
        echo "--check: report overlapping / mis-attributed labels after rendering"
        return 0
        ;;
      *)
        if [[ -z "$input" ]]; then
          input="$1"
        elif [[ -z "$output" ]]; then
          output="$1"
        else
          echo "Error: unexpected argument: $1"
          return 1
        fi
        shift
        ;;
    esac
  done

  # Find mmdc binary
  local mmdc_bin
  if command -v mmdc &>/dev/null; then
    mmdc_bin="mmdc"
  elif [[ -x "$HOME/.nvm/versions/node/v24.0.1/bin/mmdc" ]]; then
    mmdc_bin="$HOME/.nvm/versions/node/v24.0.1/bin/mmdc"
  else
    echo "Error: mmdc not found. Install with: npm install -g @mermaid-js/mermaid-cli"
    return 1
  fi

  # Validate input
  if [[ -z "$input" ]]; then
    echo "Usage: mermaid2svg <input.mermaid> [output.svg] [--style <name>]"
    return 1
  fi

  if [[ ! -f "$input" ]]; then
    echo "Error: File not found: $input"
    return 1
  fi

  # Set default output
  if [[ -z "$output" ]]; then
    output="${input%.mermaid}.svg"
  fi

  # Config paths
  local config="${MERMAID_HOME}/mermaid-config.json"
  local css_file="${MERMAID_HOME}/mermaid-styles.css"

  # Named style overrides, each independently optional
  if [[ -n "$style" ]]; then
    local styled_config="${MERMAID_HOME}/mermaid-config-${style}.json"
    local styled_css="${MERMAID_HOME}/mermaid-styles-${style}.css"

    if [[ ! -f "$styled_config" ]] && [[ ! -f "$styled_css" ]]; then
      echo "Error: unknown style '${style}' — no ${styled_config##*/} or ${styled_css##*/} in ${MERMAID_HOME}"
      return 1
    fi

    [[ -f "$styled_config" ]] && config="$styled_config"
    [[ -f "$styled_css" ]] && css_file="$styled_css"
    echo "Style: ${style}"
  fi

  # Allow local config override
  [[ -f "mermaid-config.json" ]] && config="mermaid-config.json"

  echo "Converting: $input → $output"

  # Generate SVG (timeout after 30s)
  local error_output
  error_output=$("$mmdc_bin" -i "$input" -o "$output" -c "$config" -C "$css_file" 2>&1)
  local exit_code=$?

  # A Markdown input holding N diagrams does NOT produce "$output": mmdc writes
  # one file per diagram as <input>-1.svg … <input>-N.svg. Testing -f "$output"
  # therefore reported a failure on every successful .md run.
  local is_markdown=0
  case "$input" in
    *.md|*.markdown) is_markdown=1 ;;
  esac

  if [[ $exit_code -ne 0 ]]; then
    echo "Error: Failed to generate SVG"
    [[ -n "$error_output" ]] && echo "Details: $error_output"
    return 1
  fi

  if [[ $is_markdown -eq 1 ]]; then
    local produced
    produced=$(ls -1 "${input}"-*.svg 2>/dev/null)
    if [[ -z "$produced" ]]; then
      echo "Error: no diagrams produced from $input"
      [[ -n "$error_output" ]] && echo "Details: $error_output"
      return 1
    fi
    local f
    while IFS= read -r f; do
      echo "Created: $f ($(du -h "$f" | cut -f1))"
    done <<< "$produced"
    if [[ $do_check -eq 1 ]]; then
      echo "Checking overlaps..."
      python3 "${MERMAID_HOME}/mermaid-check.py" "${input}"-*.svg
      return $?
    fi
    return 0
  fi

  if [[ ! -f "$output" ]]; then
    echo "Error: Failed to generate SVG"
    [[ -n "$error_output" ]] && echo "Details: $error_output"
    return 1
  fi

  echo "Created: $output ($(du -h "$output" | cut -f1))"
  if [[ $do_check -eq 1 ]]; then
    echo "Checking overlaps..."
    python3 "${MERMAID_HOME}/mermaid-check.py" "$output"
    return $?
  fi
}
