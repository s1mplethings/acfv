try:
    import typer
    from .gui import gui_app
    from .library import library_app
    from .clips import clip_app
    from .moments import moments_app
    from .search import search_command
    from .live import live_app
    from .download import download_app
    from .review_lab import review_lab_app
    from .creator_profile import creator_profile_app
    from .creator_visual import creator_visual_app
    # from .audio_routing import audio_route_transcribe_cli  # Temporarily disabled
    
    app = typer.Typer(pretty_exceptions_enable=False, add_completion=False, no_args_is_help=True)
    
    # Only add pipeline if dependencies are available
    try:
        from .pipeline import pipeline_app
        app.add_typer(pipeline_app, name="pipe", help="Run the open-source clip workflow")
    except ImportError:
        print("Warning: Pipeline functionality not available (missing dependencies)")
    
    app.add_typer(gui_app, name="gui", help="Launch GUI")
    app.add_typer(library_app, name="library", help="Manage creators and recordings")
    app.add_typer(moments_app, name="moments", help="Build and finalize evidence moments")
    app.add_typer(clip_app, name="clip", help="Create and render reviewed clips")
    app.add_typer(live_app, name="live", help="Inspect and search active live recordings")
    app.add_typer(download_app, name="download", help="Download Twitch VODs into the Creator Library")
    app.add_typer(review_lab_app, name="review-lab", help="Launch the compact Human Review Lab")
    app.add_typer(creator_profile_app, name="creator-profile", help="Build and inspect creator-adaptive profiles")
    app.add_typer(creator_visual_app, name="creator-visual", help="Build, benchmark, and inspect Creator visual identity")
    app.command(name="search", help="Ask the grounded Creator Library")(search_command)
    # app.command(name="audio_route")(audio_route_transcribe_cli)  # Temporarily disabled
    
except ImportError:
    # Fallback if typer is not available
    import sys
    def app():
        if len(sys.argv) > 1 and sys.argv[1] == "gui":
            from .gui import _launch
            _launch()
        elif len(sys.argv) > 1 and sys.argv[1] == "review-lab":
            from acfv.human_review.gui import launch_review_lab
            launch_review_lab()
        else:
            print("Usage: acfv [gui|review-lab]")

if __name__ == "__main__":
    app()
