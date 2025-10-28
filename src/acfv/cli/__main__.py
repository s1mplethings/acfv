try:
    import typer
    from .gui import gui_app
    from .rag import rag_app
    
    app = typer.Typer(pretty_exceptions_enable=False, add_completion=False, no_args_is_help=True)
    
    # Only add pipeline if dependencies are available
    try:
        from .pipeline import pipeline_app
        app.add_typer(pipeline_app, name="pipe", help="Run end-to-end pipeline")
    except ImportError:
        print("Warning: Pipeline functionality not available (missing dependencies)")
    
    app.add_typer(gui_app, name="gui", help="Launch GUI")
    app.add_typer(rag_app, name="rag", help="Manage RAG database")
    
except ImportError:
    # Fallback if typer is not available
    import sys
    def app():
        if len(sys.argv) > 1 and sys.argv[1] == "gui":
            from .gui import _launch
            _launch()
        elif len(sys.argv) > 1 and sys.argv[1] == "rag":
            from .rag import _launch_gui
            _launch_gui()
        else:
            print("Usage: acfv [gui|rag]")

if __name__ == "__main__":
    app()
