import typer
from rich import print

gui_app = typer.Typer(no_args_is_help=True)

@gui_app.command("run")
def run():
    from acfv.app.gui import launch_gui
    print("[bold]ACFV GUI[/] launching…")
    launch_gui()
