#!/usr/bin/env bash
# parallel_launch.sh — Spawn isolated Claude Code sessions for multiple issues.
#
# Usage:
#   ./scripts/parallel_launch.sh ISSUE-123 ISSUE-124 ISSUE-125
#   ./scripts/parallel_launch.sh --project mom-ease ISSUE-123
#   ./scripts/parallel_launch.sh --dry-run ISSUE-123 ISSUE-124
#   ./scripts/parallel_launch.sh --cleanup
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
    echo "Usage: $(basename "$0") [--dry-run] [--project NAME] ISSUE-ID..."
    echo "       $(basename "$0") --cleanup"
    exit 1
}

DRY_RUN=false
CLEANUP=false
PROJECT=""
ISSUES=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)  DRY_RUN=true;     shift ;;
        --cleanup)  CLEANUP=true;     shift ;;
        --project)  PROJECT="$2";     shift 2 ;;
        --*)        echo "Unknown option: $1"; usage ;;
        *)          ISSUES+=("$1");   shift ;;
    esac
done

# ------------------------------------------------------------------
# --cleanup: remove all devflow-ISSUE-* worktrees
# ------------------------------------------------------------------
if $CLEANUP; then
    found=0
    for wt_dir in "$PROJECT_ROOT"/../devflow-ISSUE-*/; do
        [[ -d "$wt_dir" ]] || continue
        issue_id="$(basename "$wt_dir" | sed 's/^devflow-//')"
        echo "Removing worktree: $wt_dir"
        git -C "$PROJECT_ROOT" worktree remove --force "$wt_dir" 2>/dev/null || true
        git -C "$PROJECT_ROOT" branch -D "fix/$issue_id" 2>/dev/null || true
        found=$(( found + 1 ))
    done
    if [[ $found -eq 0 ]]; then
        echo "Nothing to clean."
    fi
    exit 0
fi

[[ ${#ISSUES[@]} -gt 0 ]] || usage

# ------------------------------------------------------------------
# Print summary table header
# ------------------------------------------------------------------
printf "%-15s  %-40s  %-25s\n" "Issue" "Worktree" "Branch"
printf "%-15s  %-40s  %-25s\n" "-----" "--------" "------"

for ISSUE in "${ISSUES[@]}"; do
    WORKTREE="$PROJECT_ROOT/../devflow-$ISSUE"
    BRANCH="fix/$ISSUE"
    SESSION_ID="pid-$$-$ISSUE"

    printf "%-15s  %-40s  %-25s\n" "$ISSUE" "$WORKTREE" "$BRANCH"

    $DRY_RUN && continue

    # Create worktree + branch
    git -C "$PROJECT_ROOT" worktree add "$WORKTREE" -b "$BRANCH" 2>/dev/null

    # Copy harness config into worktree
    [[ -f "$PROJECT_ROOT/CLAUDE.md" ]] && cp "$PROJECT_ROOT/CLAUDE.md" "$WORKTREE/CLAUDE.md"
    [[ -d "$PROJECT_ROOT/.claude" ]]   && cp -r "$PROJECT_ROOT/.claude" "$WORKTREE/.claude"

    # Open new Terminal.app window (macOS); gracefully degrade on non-macOS
    osascript -e "
        tell application \"Terminal\"
            activate
            do script \"export DEVFLOW_SESSION_ID='$SESSION_ID'; cd '$WORKTREE' && claude --dangerously-skip-permissions\"
        end tell
    " 2>/dev/null || {
        echo "  [warn] Terminal window unavailable for $ISSUE"
        echo "         Run manually: export DEVFLOW_SESSION_ID='$SESSION_ID'; cd '$WORKTREE' && claude"
    }
done
