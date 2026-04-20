#!/bin/bash
# Combo statusline: ccline + caveman badge.
# Claude Code pipes JSON context to stdin — forward to ccline, append caveman.

INPUT=$(cat)
CCLINE_OUT=$(printf '%s' "$INPUT" | ccline 2>/dev/null)
CAVEMAN_OUT=$(bash "$HOME/.claude/hooks/caveman-statusline.sh" 2>/dev/null)

if [ -n "$CAVEMAN_OUT" ]; then
  printf '%s %s' "$CCLINE_OUT" "$CAVEMAN_OUT"
else
  printf '%s' "$CCLINE_OUT"
fi
