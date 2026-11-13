"""PreToolUse hook: block test execution while AUTOTEST is OFF."""
import json
import re
import sys
from pathlib import Path

STATE = Path(__file__).resolve().parent.parent / "autotest.state"
TEST_CMD = re.compile(r"(pytest|py\.test|(^|[\s/\\\"'])tests[/\\])", re.IGNORECASE)


def main() -> int:
    try:
        state = STATE.read_text().strip().upper()
    except OSError:
        return 0  # missing state file means ON
    if state != "OFF":
        return 0
    try:
        command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    except (ValueError, AttributeError):
        return 0
    if TEST_CMD.search(command):
        print("AUTOTEST is OFF. Run /AUTOTEST ON to re-enable tests.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
