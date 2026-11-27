"""The console tool's entry point (``excmp.exe`` in a frozen build): ``python -m excmp`` for a program
with no Python next to it. The installer runs ``excmp.exe shell install`` to add the Explorer menu."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from excmp.cli import main  # noqa: E402
from excmp.frozen import prepare_environment  # noqa: E402

if __name__ == "__main__":
    prepare_environment()      # a frozen build: let the tools it starts find the bundled C++ runtime
    sys.exit(main())
