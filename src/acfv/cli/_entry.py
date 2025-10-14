import sys

def main(argv=None):
    """
    Console entrypoint for `acfv`.
    Usage:
        acfv [gui]
    """
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in {"-h", "--help"}:
        print("Usage: acfv [gui]")
        return 0

    cmd, *rest = argv

    if cmd == "gui":
        # Try common GUI entry locations:
        for modpath, attr in (
            ("acfv.gui", "main"),
            ("acfv.app", "main"),
            ("acfv.frontend.gui", "main"),
        ):
            try:
                module = __import__(modpath, fromlist=[attr])
                gui_main = getattr(module, attr)
                return gui_main(*rest)
            except Exception:
                continue
        print("No GUI entry found. Expected one of: acfv.gui:main / acfv.app:main / acfv.frontend.gui:main")
        return 1

    print(f"Unknown command: {cmd}")
    return 1
