#!/usr/bin/env bash
# Cleans up devflow state/ directory pollution.
#
# Context: get_session_id() in hooks/_session.py falls back to "pid-{pid}" when
# CLAUDE_SESSION_ID is absent (e.g., in subprocesses, some hook contexts).
# Each fallback creates a new state/pid-* dir with just a risk-profile.json.
# These accumulate — a single 2-day window produced 138k dirs in the past.
#
# Run on a cron (daily) or manually when `ls state/ | wc -l` grows unchecked.
# Safe to run while devflow is active: only removes pid-* dirs older than 1 hour.
set -euo pipefail

DEVFLOW_ROOT="${DEVFLOW_ROOT:-$HOME/.claude/devflow}"
STATE_DIR="$DEVFLOW_ROOT/state"

if [[ ! -d "$STATE_DIR" ]]; then
    echo "[cleanup_state] no state dir at $STATE_DIR — nothing to do"
    exit 0
fi

BEFORE=$(find "$STATE_DIR" -maxdepth 1 -type d -name 'pid-*' | wc -l | tr -d ' ')
find "$STATE_DIR" -maxdepth 1 -type d -name 'pid-*' -mmin +60 -exec rm -rf {} +
AFTER=$(find "$STATE_DIR" -maxdepth 1 -type d -name 'pid-*' | wc -l | tr -d ' ')

echo "[cleanup_state] removed $((BEFORE - AFTER)) pid-* dirs (kept $AFTER < 1h old)"
