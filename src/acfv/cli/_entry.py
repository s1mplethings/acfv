import sys

def main(argv=None):
    """
    Console entrypoint for `acfv`.
    Usage:
        acfv [gui|rag|stream-monitor|stream-monitor-ui|--help|--version]
    """
    argv = sys.argv[1:] if argv is None else argv
    
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print("Usage: acfv [gui|rag|stream-monitor|stream-monitor-ui|--help|--version]")
        print("Commands:")
        print("  gui        Launch the GUI interface")
        print("  rag        Open the RAG manager GUI")
        print("  stream-monitor  Run the background StreamGet recorder")
        print("  stream-monitor-ui  Edit the recorder config in a PyQt UI")
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

    if cmd == "rag":
        try:
            from acfv.app.rag_gui import launch_rag_gui
            return launch_rag_gui()
        except ImportError as e:
            print(f"Error: Unable to launch RAG GUI: {e}")
            print("Make sure PyQt5 is installed: pip install PyQt5")
            return 1
        except Exception as e:
            print(f"Error launching RAG GUI: {e}")
            return 1

    if cmd in {"stream-monitor", "streamcap-service", "monitor"}:
        try:
            from acfv.cli.stream_monitor import main as stream_monitor_main
            return stream_monitor_main(rest)
        except Exception as e:
            print(f"Error running stream monitor: {e}")
            return 1

    if cmd in {"stream-monitor-ui", "monitor-ui"}:
        try:
            from acfv.cli.stream_monitor_ui import main as stream_monitor_ui_main
            return stream_monitor_ui_main(rest)
        except Exception as e:
            print(f"Error launching stream monitor UI: {e}")
            return 1

    print(f"Unknown command: {cmd}")
    print("Use 'acfv --help' for available commands")
    return 1
