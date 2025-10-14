from __future__ import annotations

# Minimal Worker placeholder (GUI threads / signals replaced later)
class Worker:
    def __init__(self, func, parent=None, *args, **kwargs):
        self.func = func
    def start(self):
        try:
            self.func()
        except Exception:  # noqa: BLE001
            pass

__all__ = ["Worker"]
