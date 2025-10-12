from pathlib import Path

def fetch_vod(src: str, workdir: str) -> str:
    Path(workdir).mkdir(parents=True, exist_ok=True)
    if src.startswith("http"):
        return str(Path(workdir) / "input.mp4")  # TODO: 下载实现
    return src
