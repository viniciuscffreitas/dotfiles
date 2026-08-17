# dotfiles

Personal dev environment: Claude Code configuration, shell setup, and CLI tooling.

`~/.claude` is a symlink to `claude/` in this repo, so editing either path edits
the same files.

## Layout

- `claude/` — Claude Code config: `CLAUDE.md`, hooks, skills, slash commands
- `shell/` — shell configuration
- `bin/`, `etc/`, `tools/` — CLI helpers and their support files
- `install.sh` / `install.ps1` — environment setup for macOS/Linux and Windows

## Install

```bash
./install.sh                      # macOS / Linux
powershell -File install.ps1      # Windows
```

`install.sh` never overwrites an existing `~/.claude/settings.json`. That file is
gitignored and evolves on the machine, so the copy already there wins; the script
backs it up and moves on. Only a machine without one gets seeded from
`claude/settings.template.json`, and then the `__PLACEHOLDER__` values in it need
filling in by hand.

## What is not in this repo

Anything Claude Code downloads or regenerates: `claude/plugins/` (marketplaces and
caches), transcripts under `claude/projects/`, file history, telemetry. Also
`claude/settings.json` itself, because it holds secrets.

So a fresh machine needs these wired up by hand after `install.sh`:

**Plugins**

```bash
claude plugin install frontend-design@claude-plugins-official
# devloop-local is a directory marketplace: ~/Developer/devloop-plugin-src
```

**MCP servers** — `context7`, `gitnexus`, `posthog`, `sentry`, `skills-sh`.
`gitnexus` also installs its skills: `gitnexus setup -c claude`.

**Skills** — `claude/skills/vini-*` are symlinks into `~/Developer/vini-personal`,
so that repo has to be cloned for them to resolve.
