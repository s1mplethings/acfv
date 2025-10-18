import sys

def main(argv=None):
    """
    Console entrypoint for `acfv`.
    Usage:
        acfv [gui|--help|--version]
    """
    argv = sys.argv[1:] if argv is None else argv
    
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print("Usage: acfv [gui|--help|--version]")
        print("Commands:")
        print("  gui        Launch the GUI interface")
        print("  --version  Show version information")
        print("  --help     Show this help message")
        return 0
    
    if argv[0] in {"--version", "-v", "version"}:
        try:
            from acfv import __version__
            print(f"acfv {__version__}")
        except ImportError:
            print("acfv 0.1.0")
        return 0

    cmd, *rest = argv

    if cmd == "gui":
        try:
            from acfv.gui import main as gui_main
            return gui_main(*rest)
        except ImportError as e:
            print(f"Error: Unable to launch GUI: {e}")
            print("Make sure PyQt5 is installed: pip install PyQt5")
            return 1
        except Exception as e:
            print(f"Error launching GUI: {e}")
            return 1

    print(f"Unknown command: {cmd}")
    print("Use 'acfv --help' for available commands")
    return 1
