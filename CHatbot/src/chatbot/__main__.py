"""Package entry point: `python -m chatbot` launches the Streamlit UI."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    """Delegate to `streamlit run` on the frontend module."""
    from streamlit.web import cli as stcli

    frontend = Path(__file__).with_name("frontend.py")
    sys.argv = ["streamlit", "run", str(frontend)]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
