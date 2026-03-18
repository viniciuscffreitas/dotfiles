# /spec

Start spec-driven development. The text after `/spec` is the task description.

If the user provided a description after `/spec`, use it immediately — do NOT ask for clarification or re-request it in quotes. Just proceed with the spec-driven-dev workflow using whatever text was provided.

If no description was provided, ask: "What do you want to build or fix?" — accept the next message as the description, with or without quotes.

Invoke `devflow:spec-driven-dev` with the description.
Auto-detects: feature (new functionality) vs bugfix (existing broken behavior).

Examples: `/spec add pagination to users`, `/spec fix: photos not loading on iOS`
