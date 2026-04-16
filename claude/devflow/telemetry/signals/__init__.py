"""Behavior-signal detectors — post-hoc analysis of Claude Code transcripts.

Complements live hooks by surfacing cross-session anti-patterns:
  - edit_thrashing:  same file edited N+ times in one session
  - error_loop:      M+ consecutive tool failures without recovery
  - restart_cluster: multiple sessions started within a short window on the same cwd

Each detector is a pure function over already-parsed events — tests swap the
transcript loader for in-memory fixtures. See tests/fixtures/*.jsonl.
"""
