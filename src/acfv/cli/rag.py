import typer
from rich import print

rag_app = typer.Typer(no_args_is_help=False, invoke_without_command=True, help="Manage the RAG database.")


@rag_app.callback()
def _entry(ctx: typer.Context) -> None:
    """Launch the RAG GUI when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        _launch_gui()


@rag_app.command("gui")
def gui() -> None:
    """Open the dedicated RAG manager GUI."""
    _launch_gui()


def _launch_gui() -> None:
    try:
        from acfv.app.rag_gui import launch_rag_gui
    except ImportError as exc:  # pragma: no cover - GUI dependencies
        print(f"[red]无法启动 RAG GUI: {exc}[/red]")
        print("请确保已安装 PyQt5: pip install PyQt5")
        raise typer.Exit(code=1)
    except Exception as exc:  # pragma: no cover
        print(f"[red]RAG GUI 启动失败: {exc}[/red]")
        raise typer.Exit(code=1)
    launch_rag_gui()


def main() -> None:  # pragma: no cover - CLI entry
    rag_app()
