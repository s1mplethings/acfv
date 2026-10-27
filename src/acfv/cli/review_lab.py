from __future__ import annotations

from pathlib import Path

import typer


review_lab_app = typer.Typer(no_args_is_help=False, invoke_without_command=True)


@review_lab_app.callback()
def review_lab(
    ctx: typer.Context,
    test_db: bool = typer.Option(False, "--test-db", help="Use isolated human_review_test.sqlite"),
    source_root: Path | None = typer.Option(None, "--source-root", file_okay=False, help="Canonical review evidence root"),
    output_root: Path | None = typer.Option(None, "--output-root", file_okay=False, help="Export folder"),
) -> None:
    """Launch the compact, single-window Human Review Lab."""
    if ctx.invoked_subcommand is not None:
        return
    from acfv.human_review.gui import launch_review_lab

    raise typer.Exit(code=launch_review_lab(test_db=test_db, source_root=source_root, output_root=output_root))


__all__ = ["review_lab_app"]
