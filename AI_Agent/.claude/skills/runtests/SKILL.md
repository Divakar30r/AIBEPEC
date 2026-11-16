---
name: runtests
description: Run the project's pytest suite under tests/. Test modules are never executed automatically; they only run when the user invokes this skill.
argument-hint: "[pytest args, e.g. -k graph]"
disable-model-invocation: true
---

# RunTests

Arguments received: `$ARGUMENTS` (optional extra pytest arguments)

1. From the project root run `uv run pytest $ARGUMENTS` (the tests need no network or database: the LLM is faked and the table lookup is patched).
2. Report the pass/fail counts. For each failure give the test name and the assertion or error.
3. Do not edit code to make tests pass unless the user asks you to.
