# devflow sg rules

Structural code checks powered by [ast-grep](https://ast-grep.github.io). Rules live as YAML files and are applied automatically by the `file_checker` hook on every Write/Edit.

## Why ast-grep

Text-based tools (`grep`, `ripgrep`) match substrings and can't distinguish a function call from a comment or a string literal. ast-grep parses the file into an AST and matches structural patterns — zero false positives on things like `print` inside `fingerprint`, TODO in a comment, or `debugger` inside a string.

## Installation

devflow treats `sg` as optional. When missing, rule enforcement silently skips.

```bash
brew install ast-grep            # macOS
cargo install ast-grep --locked  # cross-platform
npm install -g @ast-grep/cli     # node users
```

After installing, a new session will show `AST_GREP=present` in the project profile.

## How rules are resolved

Two sources, merged:

1. **Global (shipped with devflow):** `~/.claude/devflow/sg-rules/*.yml`
2. **Project override:** `<project_root>/.claude/sg-rules/*.yml`

Project rules override global rules with the same `id`. To disable a shipped rule in one project, drop a same-`id` rule with a harmless pattern under `.claude/sg-rules/`.

## Rule format

Uses ast-grep's native YAML format. Devflow reads only four top-level fields for metadata (`id`, `language`, `severity`, `message`) — everything else is passed to `sg scan` verbatim.

```yaml
id: no-print-dart                        # unique, used for override resolution
language: dart                           # matched against file extension
message: "use a logger instead of print()"
severity: warning                        # warning | error | info
files:                                   # optional — glob allowlist
  - "lib/**/*.dart"
ignores:                                 # optional — glob denylist
  - "**/test/**"
rule:
  pattern: print($$$)                    # $$$ = zero or more, $_ = single node
```

See [ast-grep rule reference](https://ast-grep.github.io/reference/yaml.html) for the full rule DSL (`all`, `any`, `not`, `inside`, `has`, regex, kind, etc.).

## Language mapping

File extensions are mapped to ast-grep languages:

| Extension | Language |
|-----------|----------|
| `.dart` | dart |
| `.ts` | typescript |
| `.tsx` | tsx |
| `.js` | javascript |
| `.jsx` | jsx |
| `.py` | python |
| `.go` | go |
| `.rs` | rust |
| `.java` | java |

Rules with a language that doesn't match the edited file are skipped — no spawn cost.

## Shipped rules

- `no-print-dart` — `print()` outside `test/` in Dart
- `no-console-log-ts` — `console.{log,warn,error}` in production TS/TSX
- `no-debugger-ts` — stray `debugger;` in TS/TSX

## Adding a rule

1. Drop a `.yml` file in `~/.claude/devflow/sg-rules/` (global) or `<project>/.claude/sg-rules/` (project-scoped).
2. Pick a stable `id` — it's the key for override resolution.
3. Keep patterns minimal — ast-grep is strict about structural shape.
4. Test it manually: `sg scan --rule <your-file>.yml <target-file>`

Broken YAML is skipped at load time with a stderr log — rules never crash the hook.

## What this is not

- **Not blocking.** sg findings appear in `[devflow quality]` output as warnings, same as file-size warnings. `pre_push_gate` stays regex-based for now.
- **Not a replacement for Grep.** For text, comments, markdown, and configs, keep using Grep. ast-grep only matches parseable source.
- **Not autofixing.** v1 is detection only. `sg scan --fix` is a possible follow-up.
