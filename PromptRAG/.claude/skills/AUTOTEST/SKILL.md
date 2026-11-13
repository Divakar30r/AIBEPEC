---
name: AUTOTEST
description: Turn automatic test execution ON or OFF for this project. While OFF, nothing under the tests folder is executed until it is turned ON again.
argument-hint: ON|OFF
disable-model-invocation: true
---

# AUTOTEST

Argument received: `$ARGUMENTS`

1. Normalise the argument to upper case. If it is not exactly `ON` or `OFF`, reply `Usage: /AUTOTEST ON|OFF` and stop without changing anything.
2. Write the single word `ON` or `OFF` (no extra text) to `.claude/autotest.state` in the project root.
3. Confirm the new state to the user in one line.

## While OFF
- Do not run pytest or anything under `tests/` on your own initiative, and do not offer to.
- A PreToolUse hook (`.claude/hooks/autotest_guard.py`) also blocks such commands; if one is blocked, report that tests were skipped because AUTOTEST is OFF.
- Only `/AUTOTEST ON` re-enables tests. A request to "run the tests" does not turn it back on; remind the user to run `/AUTOTEST ON`.
