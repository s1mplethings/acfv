from __future__ import annotations

from pathlib import Path

from acfv.modular.pipeline import run_pipeline


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    run_dir = base_dir / "runs" / "demo"

    video_path = base_dir / "example.mp4"
    chat_path = base_dir / "example_chat.html"

    if not video_path.exists():
        print("Demo requires example.mp4 under src/acfv/modular")
        return

    chat_arg = str(chat_path) if chat_path.exists() else None
    result = run_pipeline(
        video_path=str(video_path),
        chat_path=chat_arg,
        config_manager=None,
        run_dir=run_dir,
    )

    clips = result.get("clips", [])
    print(f"Generated {len(clips)} clips")


if __name__ == "__main__":
    main()
