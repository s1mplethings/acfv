from __future__ import annotations

from typing import Any

from acfv.providers.download import (
    download_twitch_vod as _download_twitch_vod,
    parse_twitch_vod_id as _parse_twitch_vod_id,
    resolve_video_source,
)


def fetch_vod(src: str, workdir: str, config_manager: Any = None) -> str:
    return resolve_video_source(src, workdir, config_manager=config_manager)
