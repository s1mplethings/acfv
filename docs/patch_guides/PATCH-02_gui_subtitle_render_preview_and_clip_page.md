# PATCH-02: GUI Subtitle Render + Preview + Clip Settings Page

> Scope: add subtitle burn-in preview/full render in GUI, plus move clip settings into the same tab.

## 0) Goals (this patch only)
Inputs:
- User selects video file (local mp4 or downloaded VOD).
- User selects subtitle file (default: `work/subtitles_streamer.ass` / `.srt`).

Outputs:
- `work/preview_subtitle_<style>.mp4` (5-15s preview).
- `out/<video_name>__sub_<style>.mp4` (optional full render).

GUI:
- New tab: Subtitle Preview/Render + Clip Settings.
- Move all clip-related settings from Run page to this combined tab.

## 1) References (URLs in code blocks)
1.1 Subtitles edit (SRT/ASS)
```
https://github.com/tkarabela/pysubs2
https://pysubs2.readthedocs.io/
```

1.2 Burn-in (FFmpeg libass)
```
https://ffmpeg.org/ffmpeg-filters.html
```

1.3 Preview playback (Qt Multimedia)
```
https://doc.qt.io/qt-6/qmediaplayer.html
https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/index.html
```

## 2) Render approach (core logic)
2.1 Must use ASS
- Styles and effects land in ASS. FFmpeg subtitles filter uses libass.

2.2 Preview = cut segment + shift/crop subtitle timeline
User selects:
- preview_start (sec)
- preview_duration (sec, default 10)

Steps:
1) Build temp preview subtitle: `tmp_preview.ass`
   - shift all events by `-preview_start`
   - drop events outside [0, preview_duration]
2) FFmpeg:
   - `-ss preview_start -t preview_duration -i video`
   - `-vf subtitles=tmp_preview.ass`
   - output to `work/preview_subtitle_<style>.mp4`

2.3 Full render (burn-in)
- `-vf subtitles=<styled.ass>` to `out/<video>__sub_<style>.mp4`
- audio: copy or AAC (align with existing default behavior)

## 3) Style presets
Add presets (at least 5):
- clean (white + black outline)
- bold (bigger + thicker)
- anime_pop (thicker outline + heavier shadow)
- minimal (smaller + light outline)
- top_caption (top aligned)

Implementation:
- `assets/subtitle_styles/presets.json`
- Use `pysubs2` to edit `subs.styles["Default"]`
- Save `work/subtitles_streamer__<style>.ass`

## 4) Backend modules (new)
Add a reusable backend service (GUI and CLI both call):
- `subtitle_style.py`:
  - `apply_style_preset(in_ass, preset_name, out_ass)`
- `subtitle_preview.py`:
  - `make_preview_ass(in_ass, start, duration, out_ass)`
  - `render_preview(video, preview_ass, out_mp4)` (ffmpeg)
- `subtitle_burnin.py`:
  - `burn_in(video, styled_ass, out_mp4)` (ffmpeg)
- `ffmpeg_runner.py`:
  - check ffmpeg, run cmd, capture stderr, structured error

## 5) CLI entry (optional but recommended)
New CLI:
- `acfv render-subtitles --video ... --subs ... --style clean --preview 10 --start 120`
- `acfv render-subtitles --video ... --subs ... --style clean --full`

GUI should call the same functions as CLI.

## 6) GUI: Subtitle Preview/Render tab
MVP UI:
- Video file picker
- Subtitle file picker (default: `work/subtitles_streamer.ass`)
- Style dropdown
- Preview start/duration
- Buttons:
  - Generate preview
  - Play preview
  - Render full

Playback:
- Use `QMediaPlayer + QVideoWidget` if available
- Fallback: `os.startfile(preview_mp4)` on Windows

## 7) GUI: Clip Settings (merged into Subtitle Preview/Render)
- Move all clip-related controls off the Run page.
- Merge clip settings into the Subtitle Preview/Render tab.
- Run page shows only:
  - summary of current clip settings
  - run buttons
- Use shared settings model/state so pipeline reads Clip Settings, not Run page widgets.

## 8) Acceptance Criteria (AC)
- Preview generate -> `work/preview_subtitle_<style>.mp4` exists.
- Preview playback works (player or system open).
- Full render -> `out/<video>__sub_<style>.mp4` exists.
- Clip settings moved into the Subtitle Preview/Render tab; run uses those settings.

## 9) Verify
```
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

## 10) Rollback
- `git apply -R patch.diff`
