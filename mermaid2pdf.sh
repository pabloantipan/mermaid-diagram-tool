#!/bin/bash
# ===========================================
# AFP PlanVital - Mermaid to PDF Converter
# ===========================================
# Usage: mermaid2pdf <input.mermaid> [output] [options]
#
# Options:
#   --simple    Logo overlay only (no header)
#   --nologo    No branding at all
#   --png       Output as PNG instead of PDF
#
# Examples:
#   mermaid2pdf diagram.mermaid
#   mermaid2pdf diagram.mermaid output.pdf
#   mermaid2pdf diagram.mermaid --simple
#   mermaid2pdf diagram.mermaid --png
# ===========================================

MERMAID_HOME="${MERMAID_HOME:-$HOME/.mermaid}"

mermaid2pdf() {
  local input=""
  local output=""
  local mode="header"  # header, simple, nologo
  local format="pdf"   # pdf, png

  # Parse arguments
  for arg in "$@"; do
    case "$arg" in
      --simple)
        mode="simple"
        ;;
      --nologo)
        mode="nologo"
        ;;
      --png)
        format="png"
        ;;
      *)
        if [[ -z "$input" ]]; then
          input="$arg"
        elif [[ -z "$output" ]]; then
          output="$arg"
        fi
        ;;
    esac
  done

  # Validate input
  if [[ -z "$input" ]]; then
    echo "Usage: mermaid2pdf <input.mermaid> [output] [--simple|--nologo] [--png]"
    echo ""
    echo "Options:"
    echo "  --simple    Logo overlay only (no header)"
    echo "  --nologo    No branding at all"
    echo "  --png       Output as PNG instead of PDF"
    return 1
  fi

  if [[ ! -f "$input" ]]; then
    echo "Error: File not found: $input"
    return 1
  fi

  # Set default output
  if [[ -z "$output" ]]; then
    output="${input%.mermaid}.${format}"
  fi

  # Config paths
  local config="${MERMAID_HOME}/mermaid-config.json"
  local css_file="${MERMAID_HOME}/mermaid-styles.css"
  local logo="${MERMAID_HOME}/planvital-logo.png"

  # Allow local config override
  [[ -f "mermaid-config.json" ]] && config="mermaid-config.json"

  # Temp files with unique IDs
  local uid="$$"
  local temp_diagram="/tmp/mermaid_diagram_${uid}.png"
  local temp_header="/tmp/mermaid_header_${uid}.png"
  local temp_final="/tmp/mermaid_final_${uid}.png"
  local temp_logo="/tmp/mermaid_logo_${uid}.png"

  echo "Converting: $input (mode: $mode, format: $format)"

  # Step 1: Generate PNG from mermaid (scale 2 for good quality without oversizing)
  if ! mmdc -i "$input" -o "$temp_diagram" -c "$config" -C "$css_file" --scale 2 -b transparent 2>/dev/null; then
    echo "Error: Failed to generate diagram"
    rm -f "$temp_diagram"
    return 1
  fi

  # Step 2: Apply branding based on mode
  case "$mode" in
    header)
      if command -v magick &> /dev/null && [[ -f "$logo" ]]; then
        echo "Creating document header..."

        # Extract title from mermaid file (comment format: %% Title: ...)
        local title=""
        title=$(grep -m1 "^%% Title:" "$input" | sed 's/^%% Title:[[:space:]]*//')
        [[ -z "$title" ]] && title=$(basename "$input" .mermaid)

        # Get diagram dimensions
        local diagram_width=$(magick identify -format "%w" "$temp_diagram")
        local header_height=120
        local logo_height=80
        local padding=40

        # Create header with white background
        magick -size "${diagram_width}x${header_height}" xc:white "$temp_header"

        # Add title text on left (dark gray for softer contrast)
        magick "$temp_header" \
          -gravity NorthWest \
          -font "Helvetica-Bold" -pointsize 42 -fill "#374151" \
          -annotate "+${padding}+40" "$title" \
          "$temp_header"

        # Add logo on right
        magick "$logo" -resize "x${logo_height}" "$temp_logo"
        magick "$temp_header" "$temp_logo" \
          -gravity NorthEast \
          -geometry "+${padding}+20" \
          -composite "$temp_header"

        # Add separator line at bottom of header
        magick "$temp_header" \
          -stroke "#CCCCCC" -strokewidth 1 \
          -draw "line 0,$((header_height-1)) ${diagram_width},$((header_height-1))" \
          "$temp_header"

        # Flatten diagram first to preserve text, then append
        magick "$temp_diagram" -background white -flatten "$temp_diagram"
        magick "$temp_header" "$temp_diagram" -append "$temp_final"
        mv "$temp_final" "$temp_diagram"
        rm -f "$temp_header" "$temp_logo"
      fi
      ;;

    simple)
      if command -v magick &> /dev/null && [[ -f "$logo" ]]; then
        echo "Adding logo overlay..."

        local diagram_width=$(magick identify -format "%w" "$temp_diagram")
        local logo_width=$((diagram_width / 7))

        magick "$logo" -resize "${logo_width}x" "$temp_logo"
        # Flatten diagram first, then composite logo
        magick "$temp_diagram" -background white -flatten "$temp_diagram"
        magick "$temp_diagram" "$temp_logo" \
          -gravity NorthEast \
          -geometry "+30+30" \
          -composite "$temp_final"
        mv "$temp_final" "$temp_diagram"
        rm -f "$temp_logo"
      fi
      ;;

    nologo)
      # No branding - diagram as-is
      ;;
  esac

  # Step 3: Convert to final format
  if [[ "$format" == "pdf" ]]; then
    # Get image dimensions and calculate if resize needed
    local img_width=$(magick identify -format "%w" "$temp_diagram")
    local max_width=2400  # Max width for reasonable PDF page

    # Resize if too wide
    if [[ "$img_width" -gt "$max_width" ]]; then
      echo "Resizing for optimal page size..."
      magick "$temp_diagram" -resize "${max_width}x>" "$temp_diagram"
    fi

    # Convert to PDF with proper density
    if ! magick "$temp_diagram" -density 150 -quality 95 "$output" 2>/dev/null; then
      # Fallback to sips if ImageMagick fails
      if ! sips -s format pdf "$temp_diagram" --out "$output" &> /dev/null; then
        echo "Error: Failed to convert to PDF"
        rm -f "$temp_diagram"
        return 1
      fi
    fi
  else
    mv "$temp_diagram" "$output"
  fi

  # Cleanup
  rm -f "$temp_diagram" "$temp_header" "$temp_final" "$temp_logo"

  echo "Created: $output"
}
