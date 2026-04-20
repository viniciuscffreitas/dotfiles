#!/bin/bash
# Tools status + rebuild helper for token-saving stack.
# Usage:
#   tools-status.sh                  # print status of CRG + CodeSight + Caveman in cwd
#   tools-status.sh rebuild          # force rebuild CRG + CodeSight wiki
#   tools-status.sh clean            # wipe .code-review-graph + .codesight (CAREFUL)

set -e

CMD="${1:-status}"
REPO="$(pwd)"

line() { printf '\n=== %s ===\n' "$1"; }

case "$CMD" in
  status)
    line "Caveman (global)"
    if [ -f "$HOME/.claude/.caveman-active" ]; then
      printf 'mode: %s\n' "$(cat "$HOME/.claude/.caveman-active")"
    else
      echo 'flag missing (SessionStart hook not run or disabled)'
    fi

    line "code-review-graph ($REPO)"
    if [ -d "$REPO/.code-review-graph" ]; then
      uvx --from code-review-graph code-review-graph status 2>/dev/null || echo 'status failed'
      printf 'DB size: %s\n' "$(du -sh "$REPO/.code-review-graph" | cut -f1)"
    else
      echo 'not installed in this repo'
    fi

    line "CodeSight ($REPO)"
    if [ -d "$REPO/.codesight" ]; then
      printf 'wiki articles: %s\n' "$(ls "$REPO/.codesight/wiki/"*.md 2>/dev/null | wc -l | tr -d ' ')"
      printf 'total size: %s\n' "$(du -sh "$REPO/.codesight" | cut -f1)"
      if [ -f "$REPO/.codesight/wiki/index.md" ]; then
        printf 'last generated: %s\n' "$(stat -f '%Sm' "$REPO/.codesight/wiki/index.md")"
      fi
    else
      echo 'not installed in this repo'
    fi

    line "MCP servers in $REPO/.mcp.json"
    if [ -f "$REPO/.mcp.json" ]; then
      python3 -c "import json; d=json.load(open('$REPO/.mcp.json')); print('\n'.join(d.get('mcpServers',{}).keys()))"
    else
      echo 'no .mcp.json'
    fi
    ;;

  rebuild)
    line "rebuilding code-review-graph"
    uvx --from code-review-graph code-review-graph build

    line "rebuilding CodeSight wiki"
    npx --yes codesight --wiki

    echo 'done.'
    ;;

  clean)
    printf 'Wipe .code-review-graph and .codesight in %s? (y/N) ' "$REPO"
    read -r ans
    if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
      rm -rf "$REPO/.code-review-graph" "$REPO/.codesight"
      echo 'wiped.'
    else
      echo 'aborted.'
    fi
    ;;

  *)
    echo "Usage: tools-status.sh [status|rebuild|clean]"
    exit 1
    ;;
esac
