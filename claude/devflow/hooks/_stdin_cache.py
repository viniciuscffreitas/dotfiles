"""Single-read stdin cache for devflow hooks.

stdin can only be read once per process. This module reads it at first access
and caches the result so both _session.py and _util.read_hook_stdin() share
the same parsed payload without consuming stdin twice.
"""
from __future__ import annotations

import json
import sys

_data: dict = {}
_read: bool = False


def get() -> dict:
    global _data, _read
    if not _read:
        _read = True
        try:
            raw = sys.stdin.read()
            if raw.strip():
                _data = json.loads(raw)
        except Exception:
            pass
    return _data
