"""Force UTF-8 as default text encoding for open() calls.

Python on Windows may default to a legacy ANSI/GBK code page causing
UnicodeDecodeError when reading UTF-8 files without specifying encoding.
This module is auto-imported by the Python startup sequence (unless -S is used).

If you need to disable this behavior for debugging or special cases, set
environment variable DISABLE_UTF8_FORCE=1 before launching the program.
"""
from __future__ import annotations
import os
import builtins

if not os.environ.get("DISABLE_UTF8_FORCE"):
    _orig_open = builtins.open

    def _utf8_open(file, mode='r', *args, **kwargs):  # type: ignore[override]
        # Only patch text modes where encoding not explicitly provided
        if 'b' not in mode and 'encoding' not in kwargs:
            kwargs['encoding'] = 'utf-8'
            # Use 'replace' rather than 'strict' to avoid hard crashes on rare
            # unexpected byte sequences; adjust to 'strict' if you prefer failure.
            kwargs.setdefault('errors', 'replace')
        return _orig_open(file, mode, *args, **kwargs)

    builtins.open = _utf8_open  # type: ignore
