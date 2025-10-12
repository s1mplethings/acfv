import typer
from .pipeline import pipeline_app
from .gui import gui_app

app = typer.Typer(pretty_exceptions_enable=False, add_completion=False, no_args_is_help=True)
app.add_typer(pipeline_app, name="pipe", help="Run end-to-end pipeline")
app.add_typer(gui_app, name="gui", help="Launch GUI")

if __name__ == "__main__":
    app()
