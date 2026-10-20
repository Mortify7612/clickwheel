"""Entry point for the frozen (PyInstaller) app."""

import os
import sys

# Windowed builds on Windows have no console: stdout/stderr are None, and any
# print or traceback would crash the app.
for name in ("stdout", "stderr"):
    if getattr(sys, name) is None:
        setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))

from clickwheel import main  # noqa: E402

raise SystemExit(main())
