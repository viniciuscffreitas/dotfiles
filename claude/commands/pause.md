# /pause

Pauses the active spec, unblocking session exit.

## Usage

```
/pause
```

## What it does

1. Reads `~/.claude/devflow/state/<session>/active-spec.json`
2. Changes status from `IMPLEMENTING` or `PENDING` to `PAUSED`
3. Saves the updated file
4. The `spec_stop_guard.py` no longer blocks session exit

## When to use

- Need to exit the session but the stop guard is blocking
- Want to pause a spec to work on something else
- Need to close terminal urgently

## Resuming

In the next session, if there is a `PAUSED` state:
- `post_compact_restore.py` shows there was a paused spec
- You can resume with `/spec` referencing the existing plan

## Implementation

Execute via Bash:

```bash
python3 -c "
import json
from pathlib import Path
import os

session_id = os.environ.get('CLAUDE_SESSION_ID', 'default')
state_file = Path.home() / '.claude' / 'devflow' / 'state' / session_id / 'active-spec.json'
if state_file.exists():
    data = json.loads(state_file.read_text())
    data['status'] = 'PAUSED'
    state_file.write_text(json.dumps(data, indent=2))
    print(f'Spec paused: {data.get(\"plan_path\", \"unknown\")}')
else:
    print('No active spec to pause.')
"
```
