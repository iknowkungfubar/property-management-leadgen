"""Thin wrapper: adds the project to sys.path and launches the sidecar.

Works both in development (python runner.py) and when bundled
by PyInstaller (dist/python-sidecar/python-sidecar).
"""

import sys
from pathlib import Path

# Determine the base directory
# When bundled by PyInstaller, __file__ is inside the _internal dir
_base = Path(__file__).resolve().parent

# Look for the 'src' package: first in _internal, then next to the binary
_src_dirs = [
    _base / "_internal" / "src",
    _base / "src",
    _base.parent / "src",
]

for _d in _src_dirs:
    if _d.is_dir() and str(_d.parent) not in sys.path:
        sys.path.insert(0, str(_d.parent))
        break

from src.main import main  # noqa: E402

if __name__ == "__main__":
    main()
