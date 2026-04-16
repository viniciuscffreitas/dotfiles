"""
Boundary worker — runs detached after stop_dispatcher identifies COMPLETED.

Launched via Popen(start_new_session=True), so it survives the dispatcher's
exit and never blocks the user's next prompt.

Session context (CLAUDE_SESSION_ID, cwd) is inherited from the dispatcher
process via environment — hooks fall back to these instead of stdin.

Logs to telemetry/boundary_worker.log since stderr is /dev/null.

Env vars:
  DEVFLOW_SKIP_JUDGE=1  Set by dispatcher when oversight=strict caused the
                        judge to already run synchronously.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import sys
from pathlib import Path

_HOOKS_DIR = Path(__file__).parent
_DEVFLOW_ROOT = _HOOKS_DIR.parent
_LOG_PATH = Path.home() / ".claude" / "devflow" / "telemetry" / "boundary_worker.log"

sys.path.insert(0, str(_HOOKS_DIR))
sys.path.insert(0, str(_DEVFLOW_ROOT))


def _setup_logging() -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(_LOG_PATH),
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        force=True,  # reconfigure even if already set (test isolation)
    )


def _run_hook(name: str) -> None:
    """Import and call hook's main(). Failures are logged, never raised."""
    try:
        spec = importlib.util.spec_from_file_location(
            f"devflow_bw_{name}", _HOOKS_DIR / f"{name}.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.main()
        logging.info("%s → exit %s", name, result)
    except SystemExit as e:
        logging.warning("%s called sys.exit(%s)", name, e.code)
    except Exception as e:
        logging.error("%s failed: %s", name, e)


def main() -> None:
    _setup_logging()

    skip_judge = os.environ.get("DEVFLOW_SKIP_JUDGE", "0") == "1"
    lock_file = os.environ.get("DEVFLOW_LOCK_FILE", "")

    try:
        if skip_judge:
            logging.info("judge skipped (already ran sync in dispatcher, oversight=strict)")
        else:
            try:
                _run_hook("post_task_judge")
            except Exception as e:
                logging.error("post_task_judge failed: %s", e)

        try:
            _run_hook("instinct_capture")
        except Exception as e:
            logging.error("instinct_capture failed: %s", e)
    finally:
        # Release lock so next task completion can spawn a fresh worker
        if lock_file:
            try:
                Path(lock_file).unlink(missing_ok=True)
            except OSError:
                pass


if __name__ == "__main__":
    main()
