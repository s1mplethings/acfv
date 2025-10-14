import typer
from rich import print

gui_app = typer.Typer(no_args_is_help=False, invoke_without_command=True)


@gui_app.callback()
def _entry(ctx: typer.Context):
    """Launch GUI when no subcommand is given."""
    if ctx.invoked_subcommand is None:
        _launch()


@gui_app.command("run")
def run():
    """Explicitly launch the GUI."""
    _launch()


def _launch():
    try:
        from acfv.app.gui import launch_gui
    except Exception as e:  # noqa: BLE001
        print(f"[red]无法导入 GUI 启动器: {e}[/red]")
        raise typer.Exit(code=1)
    print("[bold]ACFV GUI[/] launching…")
    launch_gui()
