from typing import List, Tuple
from pathlib import Path

def export_clips(media_path: str, clips: List[Tuple[float,float]], out_dir: str, settings):
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / "clips.txt").write_text(
        "\n".join([f"{a:.2f},{b:.2f}" for a,b in clips]), encoding="utf-8"
    )
