from pathlib import Path
import hashlib

import pysubs2

from acfv.backend.service import render_review_clip
from acfv.clips import ClipService
from acfv.library import ClipRenderStatus, LibraryService
from acfv.moments import MomentService


def test_query_to_clip_uses_real_existing_render_path(sample_video_path: Path, tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(
        creator_id=creator.id,
        title="Real local sample",
        local_path=sample_video_path,
    )
    moment = MomentService(library.repository).ingest_incremental(
        recording.id,
        {"segments": [{"start": 0.2, "end": 2.0, "text": "real render evidence"}]},
    )[0]
    clips = ClipService(library.repository, output_root=tmp_path / "clips")
    proposal = clips.create_proposal(
        moment.id,
        query="render evidence",
        context_before_ms=0,
        context_after_ms=1_000,
    )

    rendered = clips.render(proposal.id)

    assert rendered.render_status == ClipRenderStatus.READY
    assert rendered.output_path and Path(rendered.output_path).stat().st_size > 0
    assert (Path(rendered.output_path).parent / "work" / "selected_segments.json").is_file()
    assert (Path(rendered.output_path).parent / "work" / "clips_manifest.json").is_file()

    edited = clips.update_review(
        rendered.id,
        start_ms=300,
        end_ms=2_500,
        subtitle_text="Edited subtitle",
        subtitle_style={"preset": "clean"},
    )
    rerendered = clips.render(edited.id)
    assert rerendered.render_status == ClipRenderStatus.READY
    assert Path(rerendered.output_path).stat().st_size > 0
    assert (Path(rerendered.output_path).parent / "work" / "edited_subtitle_styled.ass").is_file()


def test_existing_renderer_burns_supplied_bilingual_ass(sample_video_path: Path, tmp_path: Path) -> None:
    subs = pysubs2.SSAFile()
    subs.events.append(pysubs2.SSAEvent(start=0, end=1500, text=r"中文字幕\NEnglish subtitle"))
    ass = tmp_path / "bilingual.ass"
    subs.save(str(ass))
    clean = tmp_path / "clean.mp4"
    bilingual = tmp_path / "bilingual.mp4"
    render_review_clip(video_path=str(sample_video_path), output_path=str(clean), start_ms=0, end_ms=2_000)
    render_review_clip(video_path=str(sample_video_path), output_path=str(bilingual), start_ms=0, end_ms=2_000,
                       subtitle_path=str(ass))
    assert clean.is_file() and bilingual.is_file()
    assert hashlib.sha256(clean.read_bytes()).digest() != hashlib.sha256(bilingual.read_bytes()).digest()
