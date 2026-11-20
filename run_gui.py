"""Start the GUI from anywhere.

The Explorer verbs (``excmp shell install``) run ``pythonw.exe run_gui.py <action> "%1"`` from a
source checkout, and Explorer starts them in the selected file's folder, where ``gui`` is not
importable and ``python -m gui`` cannot work. This file puts its own folder on ``sys.path`` first.
It is also the entry point a frozen build (PyInstaller, E3) is made from.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gui.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
