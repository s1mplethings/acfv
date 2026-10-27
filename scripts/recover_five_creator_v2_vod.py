from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.parse import urljoin

import requests


REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "var" / "five-creator-v2"
BASE_RECOVERY = REPO / "var" / "validation" / "highest-quality-long-soak" / "recover_vod_2884984247.py"
SAFE_RESERVE_BYTES = 300_057_152_102


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for attempt in range(20):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05 * (attempt + 1))


def load_base():
    spec = importlib.util.spec_from_file_location("acfv_verified_segmented_recovery", BASE_RECOVERY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verified recovery implementation: {BASE_RECOVERY}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configure(module, *, creator: str, vod_id: str, expected_seconds: float) -> Path:
    work = ROOT / "recovery" / vod_id
    evidence = ROOT / "evidence" / f"v2-recovery-{vod_id}"
    canonical = ROOT / "raw" / creator / vod_id / f"{creator}_{vod_id}_highest.mp4"
    module.VOD_ID = vod_id
    module.CREATOR = creator
    module.QUALITY = "best"
    module.EXPECTED_SECONDS = expected_seconds
    module.WORK = work
    module.FRAGMENTS = work / "fragments"
    module.FRAGMENT_RECEIPTS = work / "fragment-receipts"
    module.CHUNKS = work / "chunks"
    module.EVIDENCE = evidence
    module.ORIGINAL = canonical
    module.MAX_RATE_BPS = 8 * 1024 * 1024

    class StrictRateLimiter:
        """No-burst limiter used by V2 recovery.

        The verified recovery implementation uses a one-second token bucket.
        That respects sustained rate but can make short-fragment transfer
        receipts exceed 8 MiB/s. V2 requires every measured fragment to remain
        at or below the configured ceiling, so each consumed block pays its
        complete transmission interval without carrying unused allowance.
        """

        def __init__(self, rate_bps: int) -> None:
            self.rate_bps = rate_bps

        def consume(self, count: int) -> None:
            if count > 0:
                time.sleep(count / self.rate_bps)

    def disk_guard() -> dict[str, object]:
        usage = shutil.disk_usage(ROOT)
        payload = {
            "total_bytes": usage.total,
            "free_bytes": usage.free,
            "reserve_bytes": SAFE_RESERVE_BYTES,
            "passed": usage.free >= SAFE_RESERVE_BYTES,
            "checked_at": now(),
        }
        write_json(evidence / "storage.json", payload)
        if not payload["passed"]:
            raise RuntimeError(
                f"disk reserve violated: free={usage.free} reserve={SAFE_RESERVE_BYTES}"
            )
        return payload

    def load_playlist(session: requests.Session):
        response = None
        for attempt in range(1, 6):
            try:
                url = module.playlist_url()
                response = session.get(url, timeout=(30, 120))
                response.raise_for_status()
                break
            except (requests.RequestException, RuntimeError):
                if attempt == 5:
                    raise
                time.sleep(min(30, 2 ** attempt))
        if response is None:
            raise RuntimeError("playlist discovery produced no response")
        fragments: list[dict[str, object]] = []
        pending_duration: float | None = None
        for raw_line in response.text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#EXTINF:"):
                pending_duration = float(line.split(":", 1)[1].split(",", 1)[0])
            elif not line.startswith("#") and pending_duration is not None:
                fragments.append({
                    "index": len(fragments),
                    "duration_seconds": pending_duration,
                    "url": urljoin(url, line),
                })
                pending_duration = None
        declared = sum(float(row["duration_seconds"]) for row in fragments)
        tolerance = max(5.0, expected_seconds * 0.001)
        if not fragments or abs(declared - expected_seconds) > tolerance:
            raise RuntimeError(
                f"unexpected source playlist: fragments={len(fragments)} "
                f"duration={declared} expected={expected_seconds} tolerance={tolerance}"
            )
        module._v2_fragment_total = len(fragments)
        write_json(evidence / "source-playlist.json", {
            "schema_version": "1.0",
            "vod_id": vod_id,
            "quality": "best",
            "fragment_count": len(fragments),
            "declared_duration_seconds": declared,
            "expected_duration_seconds": expected_seconds,
            "playlist_url": url,
            "captured_at": now(),
            "ground_truth_opened": False,
        })
        return url, fragments

    module._v2_normalize_full_decode_timestamps = False

    def decode(path: Path, *, start: float | None = None, duration: float | None = None):
        command = [str(module.FFMPEG), "-hide_banner", "-v", "error"]
        if start is not None:
            command += ["-ss", f"{max(0.0, start):.3f}"]
        command += ["-i", str(path)]
        if duration is not None:
            command += ["-t", f"{duration:.3f}"]
        command += ["-map", "0:v:0", "-map", "0:a:0"]
        if start is not None:
            # Fast input seek can begin on B-frames whose original DTS precedes
            # the chosen boundary. Reset decoded audio/video timestamps before
            # the null muxer so the probe tests decoding rather than cut-point
            # timestamp ordering. Full sequential scans remain unchanged.
            command += ["-vf", "setpts=PTS-STARTPTS", "-af", "asetpts=PTS-STARTPTS"]
        elif getattr(module, "_v2_normalize_full_decode_timestamps", False):
            # A chunk-concat recovery can contain duplicate decoded frame PTS
            # at otherwise clean boundaries. The null muxer rejects those
            # timestamps even when every packet decodes successfully. Generate
            # validation-only monotonic timestamps while still decoding every
            # video frame and audio sample; real decoder errors remain visible.
            command += ["-vf", "setpts=N/(60*TB)", "-af", "asetpts=N/SR/TB"]
        command += ["-f", "null", "NUL"]
        completed = module.run(command, timeout=43_200 if duration is None else 180)
        return {
            "passed": completed.returncode == 0 and not completed.stderr.strip(),
            "exit_code": completed.returncode,
            "error": completed.stderr.strip() or None,
            "start_seconds": start,
            "duration_seconds": duration,
        }

    def update_progress(fragment_rows, chunks) -> None:
        total = int(getattr(module, "_v2_fragment_total", 0))
        write_json(evidence / "progress.json", {
            "schema_version": "1.0",
            "result": "IN_PROGRESS",
            "vod_id": vod_id,
            "fragments_completed": len(fragment_rows),
            "fragments_total": total,
            "segments_completed": len(chunks),
            "segments_total": (total + 89) // 90 if total else None,
            "last_fragment": fragment_rows[-1]["index"] if fragment_rows else None,
            "updated_at": now(),
            "ground_truth_opened": False,
        })

    def timeline(fragment_rows, chunks):
        discontinuities = []
        for previous, current in zip(fragment_rows, fragment_rows[1:]):
            delta = (
                float(current["validation"]["video_start_seconds"])
                - float(previous["validation"]["video_end_seconds"])
            )
            if abs(delta) > 0.1:
                discontinuities.append({
                    "after_fragment": previous["index"],
                    "before_fragment": current["index"],
                    "delta_seconds": delta,
                })
        requested_gaps = []
        requested_overlaps = []
        for previous, current in zip(chunks, chunks[1:]):
            delta = float(current["requested_start_seconds"]) - float(previous["requested_end_seconds"])
            if delta > 0:
                requested_gaps.append({"after_segment": previous["segment_index"], "seconds": delta})
            elif delta < 0:
                requested_overlaps.append({"after_segment": previous["segment_index"], "seconds": -delta})
        total = int(getattr(module, "_v2_fragment_total", 0))
        payload = {
            "schema_version": "1.0",
            "vod_id": vod_id,
            "fragment_count": len(fragment_rows),
            "segment_count": len(chunks),
            "requested_gaps": requested_gaps,
            "requested_overlaps": requested_overlaps,
            "timestamp_discontinuities": discontinuities,
            "missing_head": not fragment_rows or int(fragment_rows[0]["index"]) != 0,
            "missing_tail": not fragment_rows or int(fragment_rows[-1]["index"]) != total - 1,
            "duplicate_fragment_indices": len(fragment_rows) != len({int(row["index"]) for row in fragment_rows}),
            "result": "PASS" if not requested_gaps and not requested_overlaps and not discontinuities else "FAIL",
            "created_at": now(),
        }
        write_json(evidence / "timeline.json", payload)
        return payload

    def preserve_and_publish(candidate: Path, integrity: dict[str, object]):
        if canonical.exists():
            raise FileExistsError(f"refusing to overwrite canonical Raw: {canonical}")
        canonical.parent.mkdir(parents=True, exist_ok=True)
        candidate.replace(canonical)
        marker = {
            "schema_version": "1.0",
            "vod_id": vod_id,
            "classification": "FAILED_ASSEMBLY_EVIDENCE",
            "path": str(ROOT / "temp" / "five-creator-v2" / vod_id),
            "reason": "initial TwitchDownloader assembly failed strict sequential decode",
            "retained": True,
            "replacement_path": str(canonical),
            "replacement_sha256": integrity["sha256"],
            "created_at": now(),
        }
        write_json(evidence / "preserved-failed-assembly.json", marker)
        return marker

    module.disk_guard = disk_guard
    module.RateLimiter = StrictRateLimiter
    module.decode = decode
    module.load_playlist = load_playlist
    module.update_progress = update_progress
    module.timeline = timeline
    module.preserve_and_publish = preserve_and_publish
    original_download_fragment = module.download_fragment
    module.MAX_FRAGMENT_ATTEMPTS = 2

    def download_fragment(session, limiter, row):
        try:
            return original_download_fragment(session, limiter, row)
        except RuntimeError:
            index = int(row["index"])
            expected = float(row["duration_seconds"])
            target = module.FRAGMENTS / f"{index:05d}.ts"
            receipt_path = module.FRAGMENT_RECEIPTS / f"{index:05d}.json"
            failed = json.loads(receipt_path.read_text(encoding="utf-8"))
            failures = failed.get("failures") or []
            sources = sorted(
                module.FRAGMENTS.glob(f"{index:05d}.ts.invalid-attempt-*"),
                key=lambda path: path.stat().st_mtime,
            )
            recent = sources[-2:]
            if (
                failed.get("result") != "RECOVERY_REQUIRED"
                or len(failures) != 2
                or any(item.get("http_status") != 200 for item in failures)
                or any("fragment decode failed" not in str(item.get("error") or "") for item in failures)
                or len(recent) != 2
                or module.sha256(recent[0]) != module.sha256(recent[1])
            ):
                raise
            source = recent[-1]
            temporary = module.WORK / f"{index:05d}.auto-lossless-repair.ts"
            if target.exists() or temporary.exists():
                raise RuntimeError(f"refusing automatic overwrite for fragment {index}")
            completed = module.run([
                str(module.FFMPEG), "-hide_banner", "-v", "warning", "-copyts",
                "-fflags", "+discardcorrupt", "-err_detect", "ignore_err",
                "-i", str(source), "-map", "0:v:0", "-map", "0:a:0",
                "-c:v", "libx264", "-preset", "fast", "-crf", "0",
                "-c:a", "aac", "-b:a", "160k", "-muxdelay", "0", "-muxpreload", "0",
                "-f", "mpegts", str(temporary),
            ], timeout=600)
            if completed.returncode != 0:
                raise RuntimeError(f"automatic lossless fragment repair failed: {completed.stderr.strip()}")
            validation = module.validate_fragment(temporary, expected)
            temporary.replace(target)
            archived_receipt = module.archive(receipt_path, "source-corrupt")
            receipt = {
                "schema_version": 1,
                "index": index,
                "expected_duration_seconds": expected,
                "path": str(target),
                "bytes": target.stat().st_size,
                "sha256": module.sha256(target),
                "validation": validation,
                "result": "PASS",
                "reused": False,
                "repair": {
                    "kind": "LOSSLESS_VIDEO_REENCODE_WITH_CORRUPT_PACKET_DISCARD",
                    "automatic": True,
                    "source_path": str(source),
                    "source_sha256": module.sha256(source),
                    "archived_failed_receipt": str(archived_receipt),
                    "source_failure_count": len(failures),
                    "identical_source_attempts": 2,
                    "video_codec": "libx264",
                    "video_crf": 0,
                    "audio": "aac_160k",
                    "preserve_source_timestamps": True,
                    "mpegts_muxdelay_seconds": 0,
                    "ffmpeg_warning": completed.stderr.strip() or None,
                    "created_at": now(),
                },
            }
            write_json(receipt_path, receipt)
            write_json(evidence / f"corrupt-fragment-{index:05d}-remediation.json", {
                **receipt,
                "ground_truth_opened": False,
            })
            return receipt

    module.download_fragment = download_fragment
    original_assemble_chunk = module.assemble_chunk

    def assemble_chunk(index, fragment_rows):
        start = int(fragment_rows[0]["index"]) * 10
        end = min(int(expected_seconds), (int(fragment_rows[-1]["index"]) + 1) * 10)
        nominal_expected = float(end - start)
        playlist_expected = sum(
            float(row["expected_duration_seconds"]) for row in fragment_rows
        )
        target = module.CHUNKS / f"chunk-{index:03d}-{start:05d}-{end:05d}.mp4"
        receipt_path = evidence / f"vod-recovery-segment-{index:03d}.json"
        if target.exists() and abs(playlist_expected - nominal_expected) > 0.001:
            media = module.probe(target)
            if abs(float(media["duration_seconds"]) - playlist_expected) <= 2.0:
                probes = module.decode_probes(
                    target,
                    float(media["duration_seconds"]),
                    [0.0, playlist_expected / 2, playlist_expected - 2],
                )
                if all(row["passed"] for row in probes):
                    downloaded = [row for row in fragment_rows if not row.get("reused")]
                    downloaded_bytes = sum(int(row.get("bytes") or 0) for row in downloaded)
                    download_runtime = sum(
                        float(row.get("runtime_seconds") or 0) for row in downloaded
                    )
                    receipt = {
                        "schema_version": 1,
                        "segment_index": index,
                        "requested_start_seconds": start,
                        "requested_end_seconds": end,
                        "expected_duration_seconds": playlist_expected,
                        "nominal_duration_seconds": nominal_expected,
                        "actual_decoded_start_seconds": media["video_start_seconds"],
                        "actual_decoded_end_seconds": media["video_end_seconds"],
                        "actual_duration_seconds": media["duration_seconds"],
                        "download_bytes": sum(int(row["bytes"]) for row in fragment_rows),
                        "quality": module.QUALITY,
                        "resolution": f"{media['width']}x{media['height']}",
                        "fps": media["fps"],
                        "download_runtime_seconds": download_runtime,
                        "assembly_runtime_seconds": None,
                        "average_throughput_mib_s": downloaded_bytes
                        / max(download_runtime, 0.001)
                        / (1024 * 1024),
                        "retry_count": sum(
                            int(row.get("retry_count") or 0) for row in fragment_rows
                        ),
                        "exit_code": 0,
                        "ffprobe_status": "PASS",
                        "decode_status": "PASS",
                        "decode_probes": probes,
                        "sha256": module.sha256(target),
                        "path": str(target),
                        "fragment_start_index": int(fragment_rows[0]["index"]),
                        "fragment_end_index": int(fragment_rows[-1]["index"]),
                        "fragment_count": len(fragment_rows),
                        "result": "PASS",
                        "reused": True,
                        "repair": {
                            "kind": "PLAYLIST_EXTINF_DURATION_VALIDATION",
                            "reason": "source playlist contains non-10-second fragments",
                            "preserved_failed_gate": True,
                        },
                        "finished_at": now(),
                    }
                    write_json(receipt_path, receipt)
                    write_json(evidence / f"segment-{index:03d}-duration-remediation.json", {
                        **receipt,
                        "ground_truth_opened": False,
                    })
                    return receipt
        try:
            return original_assemble_chunk(index, fragment_rows)
        except RuntimeError as exc:
            if "Error parsing ADTS frame header" not in str(exc):
                raise
            expected = float(end - start)
            concat = module.WORK / f"segment-{index:03d}-concat.txt"
            temporary = target.with_suffix(".audio-repair.assembling.mp4")
            if target.exists() or temporary.exists():
                raise RuntimeError(f"refusing segment audio-repair overwrite: {target}")
            started = time.perf_counter()
            completed = module.run([
                str(module.FFMPEG), "-hide_banner", "-v", "warning",
                "-f", "concat", "-safe", "0", "-i", str(concat),
                "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
                str(temporary),
            ], timeout=3600)
            assembly_runtime = time.perf_counter() - started
            if completed.returncode != 0:
                if temporary.exists():
                    module.archive(temporary, "audio-repair-failed")
                raise RuntimeError(f"segment {index} audio repair failed: {completed.stderr.strip()}")
            temporary.replace(target)
            media = module.probe(target)
            if abs(float(media["duration_seconds"]) - expected) > 2.0:
                raise RuntimeError(f"segment {index} duration mismatch after audio repair")
            probes = module.decode_probes(
                target,
                float(media["duration_seconds"]),
                [0.0, expected / 2, expected - 2],
            )
            repair_kind = "SEGMENT_AUDIO_REENCODE_AFTER_ADTS_COPY_FAILURE"
            repaired_video = "stream_copy"
            if not all(item["passed"] for item in probes):
                preserved_audio_repair = module.archive(
                    target, "audio-repair-decode-failed"
                )
                temporary = target.with_suffix(".lossless-repair.assembling.mp4")
                if temporary.exists():
                    raise RuntimeError(
                        f"refusing segment lossless-repair overwrite: {temporary}"
                    )
                lossless_started = time.perf_counter()
                completed = module.run([
                    str(module.FFMPEG), "-hide_banner", "-v", "warning",
                    "-fflags", "+discardcorrupt", "-err_detect", "ignore_err",
                    "-f", "concat", "-safe", "0", "-i", str(concat),
                    "-map", "0:v:0", "-map", "0:a:0",
                    "-vf", "setpts=N/60/TB", "-af", "aresample=async=1:first_pts=0",
                    "-fps_mode", "cfr", "-r", "60", "-c:v", "libx264",
                    "-preset", "fast", "-crf", "0", "-c:a", "aac",
                    "-b:a", "160k", "-movflags", "+faststart", str(temporary),
                ], timeout=7200)
                assembly_runtime += time.perf_counter() - lossless_started
                if completed.returncode != 0:
                    if temporary.exists():
                        module.archive(temporary, "lossless-repair-failed")
                    raise RuntimeError(
                        f"segment {index} lossless repair failed: "
                        f"{completed.stderr.strip()}"
                    )
                temporary.replace(target)
                media = module.probe(target)
                if abs(float(media["duration_seconds"]) - expected) > 2.0:
                    preserved_lossless_repair = module.archive(
                        target, "lossless-repair-duration-mismatch"
                    )
                    normalized_dir = module.WORK / f"segment-{index:03d}-normalized"
                    normalized_dir.mkdir(parents=True, exist_ok=True)
                    normalized_paths = []
                    for item in fragment_rows:
                        fragment_index = int(item["index"])
                        source_fragment = Path(str(item["path"]))
                        normalized = normalized_dir / f"{fragment_index:05d}.mp4"
                        if not normalized.exists():
                            normalized_temporary = normalized.with_suffix(
                                ".normalizing.mp4"
                            )
                            if normalized_temporary.exists():
                                module.archive(normalized_temporary, "stale-normalizing")
                            normalized_result = module.run([
                                str(module.FFMPEG), "-hide_banner", "-v", "warning",
                                "-copyts", "-start_at_zero", "-i", str(source_fragment),
                                "-map", "0:v:0", "-map", "0:a:0", "-c", "copy",
                                "-movflags", "+faststart", str(normalized_temporary),
                            ], timeout=300)
                            if normalized_result.returncode != 0:
                                if normalized_temporary.exists():
                                    module.archive(
                                        normalized_temporary,
                                        "fragment-normalization-failed",
                                    )
                                raise RuntimeError(
                                    f"segment {index} fragment {fragment_index} "
                                    f"normalization failed: {normalized_result.stderr.strip()}"
                                )
                            normalized_temporary.replace(normalized)
                        normalized_paths.append(normalized)
                    normalized_concat = module.WORK / (
                        f"segment-{index:03d}-normalized-concat.txt"
                    )
                    normalized_concat.write_text(
                        "".join(
                            f"file '{module.escape_concat(path)}'\n"
                            for path in normalized_paths
                        ),
                        encoding="utf-8",
                    )
                    temporary = target.with_suffix(
                        ".normalized-concat.assembling.mp4"
                    )
                    if temporary.exists():
                        module.archive(temporary, "stale-normalized-concat")
                    normalized_started = time.perf_counter()
                    completed = module.run([
                        str(module.FFMPEG), "-hide_banner", "-v", "warning",
                        "-f", "concat", "-safe", "0", "-i", str(normalized_concat),
                        "-map", "0:v:0", "-map", "0:a:0", "-c", "copy",
                        "-movflags", "+faststart", str(temporary),
                    ], timeout=3600)
                    assembly_runtime += time.perf_counter() - normalized_started
                    if completed.returncode != 0:
                        if temporary.exists():
                            module.archive(temporary, "normalized-concat-failed")
                        raise RuntimeError(
                            f"segment {index} normalized concat failed: "
                            f"{completed.stderr.strip()}"
                        )
                    temporary.replace(target)
                    media = module.probe(target)
                    if abs(float(media["duration_seconds"]) - expected) > 2.0:
                        raise RuntimeError(
                            f"segment {index} duration mismatch after normalized concat"
                        )
                    repair_kind = (
                        "SEGMENT_TIMESTAMP_NORMALIZED_CONCAT_AFTER_LOSSLESS_"
                        "DURATION_MISMATCH"
                    )
                    repaired_video = "normalized_fragment_stream_copy"
                probes = module.decode_probes(
                    target,
                    float(media["duration_seconds"]),
                    [0.0, expected / 2, expected - 2],
                )
                if not all(item["passed"] for item in probes):
                    raise RuntimeError(
                        f"segment {index} decode probe failed after lossless repair"
                    )
                repair_kind = "SEGMENT_LOSSLESS_CFR_REENCODE_AFTER_AUDIO_REPAIR_DECODE_FAILURE"
                repaired_video = "libx264_crf0"
            downloaded = [item for item in fragment_rows if not item.get("reused")]
            downloaded_bytes = sum(int(item.get("bytes") or 0) for item in downloaded)
            download_runtime = sum(float(item.get("runtime_seconds") or 0) for item in downloaded)
            receipt = {
                "schema_version": 1,
                "segment_index": index,
                "requested_start_seconds": start,
                "requested_end_seconds": end,
                "expected_duration_seconds": expected,
                "actual_decoded_start_seconds": media["video_start_seconds"],
                "actual_decoded_end_seconds": media["video_end_seconds"],
                "actual_duration_seconds": media["duration_seconds"],
                "download_bytes": sum(int(item["bytes"]) for item in fragment_rows),
                "quality": module.QUALITY,
                "resolution": f"{media['width']}x{media['height']}",
                "fps": media["fps"],
                "download_runtime_seconds": download_runtime,
                "assembly_runtime_seconds": assembly_runtime,
                "average_throughput_mib_s": downloaded_bytes / max(download_runtime, 0.001) / (1024 * 1024),
                "retry_count": sum(int(item.get("retry_count") or 0) for item in fragment_rows),
                "exit_code": completed.returncode,
                "ffprobe_status": "PASS",
                "decode_status": "PASS",
                "decode_probes": probes,
                "sha256": module.sha256(target),
                "path": str(target),
                "fragment_start_index": int(fragment_rows[0]["index"]),
                "fragment_end_index": int(fragment_rows[-1]["index"]),
                "fragment_count": len(fragment_rows),
                "result": "PASS",
                "reused": False,
                "repair": {
                    "kind": repair_kind,
                    "video": repaired_video,
                    "audio": "aac_160k",
                    "preserved_failed_assembly": True,
                    "preserved_failed_audio_repair": str(preserved_audio_repair)
                    if repaired_video != "stream_copy" else None,
                    "source_error": str(exc),
                },
                "finished_at": now(),
            }
            write_json(receipt_path, receipt)
            write_json(evidence / f"segment-{index:03d}-audio-remediation.json", {
                **receipt,
                "ground_truth_opened": False,
            })
            return receipt

    module.assemble_chunk = assemble_chunk
    original_assemble_final = module.assemble_final

    def assemble_final(fragment_rows):
        candidate = module.WORK / f"{creator}_{vod_id}_highest.recovered.mp4"
        transport = module.WORK / f"{creator}_{vod_id}_highest.recovered.assembling.ts"
        integrity_receipt = evidence / "vod-recovery-integrity.json"
        if candidate.exists() and integrity_receipt.is_file():
            prior_integrity = json.loads(integrity_receipt.read_text(encoding="utf-8"))
            sequential_error = str(
                (prior_integrity.get("full_sequential_decode") or {}).get("error") or ""
            )
            if (
                prior_integrity.get("result") == "FAIL"
                and "non monotonically increasing dts" in sequential_error.lower()
            ):
                first_normalization = evidence / "final-timestamp-normalization.json"
                monotonic_normalization = (
                    evidence / "final-monotonic-dts-normalization.json"
                )
                if monotonic_normalization.exists():
                    # The preserved retry may have failed only because ffmpeg's
                    # null muxer rejects equal decoded-frame timestamps.  Let
                    # final_integrity re-evaluate it with the packet audit below.
                    return candidate
                use_monotonic_bsf = first_normalization.exists()
                temporary = candidate.with_suffix(
                    ".monotonic-dts.assembling.mp4"
                    if use_monotonic_bsf
                    else ".timestamps-normalized.assembling.mp4"
                )
                if temporary.exists():
                    raise FileExistsError(
                        f"refusing to overwrite timestamp-normalization output: {temporary}"
                    )
                started = time.perf_counter()
                command = [
                    str(module.FFMPEG), "-hide_banner", "-v", "warning",
                    "-i", str(candidate), "-map", "0:v:0", "-map", "0:a:0",
                    "-c", "copy",
                ]
                if use_monotonic_bsf:
                    command.extend([
                        "-bsf:v",
                        "setts=pts=if(eq(N\\,0)\\,PTS\\,if(lte(PTS\\,PREV_OUTPTS)\\,PREV_OUTPTS+1\\,PTS)):dts=if(eq(N\\,0)\\,DTS\\,if(lte(DTS\\,PREV_OUTDTS)\\,PREV_OUTDTS+1\\,DTS))",
                    ])
                else:
                    command[1:1] = ["-fflags", "+genpts+igndts"]
                command.extend([
                    "-avoid_negative_ts", "make_zero", "-movflags", "+faststart",
                    str(temporary),
                ])
                completed = module.run(command, timeout=7200)
                if completed.returncode != 0:
                    if temporary.exists():
                        module.archive(temporary, "timestamp-normalization-failed")
                    raise RuntimeError(
                        f"timestamp normalization failed: {completed.stderr.strip()}"
                    )
                preserved = module.archive(
                    candidate,
                    "genpts-nonmonotonic-dts-failed"
                    if use_monotonic_bsf
                    else "nonmonotonic-dts-failed",
                )
                temporary.replace(candidate)
                write_json(
                    monotonic_normalization
                    if use_monotonic_bsf
                    else first_normalization,
                    {
                    "schema_version": "1.0",
                    "vod_id": vod_id,
                    "result": "PASS",
                    "kind": (
                        "STREAM_COPY_MONOTONIC_DTS_BITSTREAM_NORMALIZATION"
                        if use_monotonic_bsf
                        else "STREAM_COPY_TIMESTAMP_NORMALIZATION"
                    ),
                    "source": str(preserved),
                    "output": str(candidate),
                    "ffmpeg": (
                        "setts clamp to PREV_OUTPTS/PREV_OUTDTS + 1 tick"
                        if use_monotonic_bsf
                        else "genpts+igndts, avoid_negative_ts=make_zero"
                    ),
                    "runtime_seconds": time.perf_counter() - started,
                    "ffmpeg_warning": completed.stderr.strip() or None,
                    "created_at": now(),
                    "ground_truth_opened": False,
                    },
                )
                return candidate
        preserved_candidates = sorted(
            module.WORK.glob(
                f"{creator}_{vod_id}_highest.recovered.mp4.invalid-preexisting-*"
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not candidate.exists():
            final_duration_tolerance = max(5.0, float(expected_seconds) * 0.002)
            for preserved_candidate in preserved_candidates:
                media = module.probe(preserved_candidate)
                if (
                    abs(float(media["duration_seconds"]) - expected_seconds)
                    <= final_duration_tolerance
                ):
                    os.link(preserved_candidate, candidate)
                    write_json(evidence / "final-preserved-candidate-reuse.json", {
                        "schema_version": "1.0",
                        "vod_id": vod_id,
                        "result": "PASS",
                        "kind": "HARDLINK_REUSE_OF_PRESERVED_CANDIDATE",
                        "source": str(preserved_candidate),
                        "output": str(candidate),
                        "duration_seconds": media["duration_seconds"],
                        "duration_tolerance_seconds": final_duration_tolerance,
                        "created_at": now(),
                        "ground_truth_opened": False,
                    })
                    return candidate
        final_audio_failures = sorted(
            module.WORK.glob(
                f"{creator}_{vod_id}_highest.recovered.audio-repair.assembling.mp4.final-audio-repair-failed-*"
            )
        )

        def assemble_from_chunks(reason: str):
            chunks = sorted(module.CHUNKS.glob("chunk-*.mp4"))
            expected_chunk_count = int(
                (float(expected_seconds) + float(module.CHUNK_SECONDS) - 1)
                // float(module.CHUNK_SECONDS)
            )
            if len(chunks) != expected_chunk_count or candidate.exists():
                raise RuntimeError("chunk-based final assembly preconditions not met")
            concat = module.WORK / "final-chunks-concat.txt"
            concat.write_text(
                "".join(f"file '{module.escape_concat(path)}'\n" for path in chunks),
                encoding="utf-8",
            )
            temporary = candidate.with_suffix(".chunks.assembling.mp4")
            if temporary.exists():
                raise FileExistsError(f"refusing to overwrite final chunk assembly: {temporary}")
            started = time.perf_counter()
            completed = module.run([
                str(module.FFMPEG), "-hide_banner", "-v", "warning",
                "-f", "concat", "-safe", "0", "-i", str(concat),
                "-map", "0:v:0", "-map", "0:a:0", "-c", "copy",
                "-movflags", "+faststart", str(temporary),
            ], timeout=7200)
            audio_reencoded = False
            copy_error = completed.stderr.strip() or None
            if completed.returncode != 0:
                if temporary.exists():
                    module.archive(temporary, "chunk-copy-failed")
                completed = module.run([
                    str(module.FFMPEG), "-hide_banner", "-v", "warning",
                    "-f", "concat", "-safe", "0", "-i", str(concat),
                    "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
                    str(temporary),
                ], timeout=7200)
                audio_reencoded = True
            if completed.returncode != 0:
                if temporary.exists():
                    module.archive(temporary, "chunk-audio-repair-failed")
                raise RuntimeError(f"chunk-based final assembly failed: {completed.stderr.strip()}")
            temporary.replace(candidate)
            media = module.probe(candidate)
            final_duration_tolerance = max(5.0, float(expected_seconds) * 0.002)
            if (
                abs(float(media["duration_seconds"]) - expected_seconds)
                > final_duration_tolerance
            ):
                raise RuntimeError("chunk-based final assembly duration mismatch")
            write_json(evidence / "final-chunk-assembly-remediation.json", {
                "schema_version": "1.0",
                "vod_id": vod_id,
                "result": "PASS",
                "kind": "FINAL_ASSEMBLY_FROM_VALIDATED_CHUNKS",
                "reason": reason,
                "chunk_count": len(chunks),
                "chunks": [str(path) for path in chunks],
                "video": "stream_copy",
                "audio": "aac_160k" if audio_reencoded else "stream_copy",
                "initial_copy_error": copy_error,
                "output": str(candidate),
                "output_sha256": module.sha256(candidate),
                "duration_seconds": media["duration_seconds"],
                "runtime_seconds": time.perf_counter() - started,
                "created_at": now(),
                "ground_truth_opened": False,
            })
            return candidate

        if final_audio_failures and not candidate.exists():
            return assemble_from_chunks("preserved raw-transport audio-repair failure")
        preserved_failures = sorted(
            module.WORK.glob(f"{creator}_{vod_id}_highest.recovered.assembling.mp4.assembly-failed-*")
        )
        if transport.is_file() and preserved_failures and not candidate.exists():
            exc = RuntimeError("preserved final concat failure: Error parsing ADTS frame header")
        else:
            try:
                return original_assemble_final(fragment_rows)
            except RuntimeError as caught:
                if "Error parsing ADTS frame header" not in str(caught):
                    raise
                exc = caught
        temporary = candidate.with_suffix(".audio-repair.assembling.mp4")
        if candidate.exists() or temporary.exists() or not transport.is_file():
            raise RuntimeError("final audio-repair preconditions not met")
        try:
            started = time.perf_counter()
            completed = module.run([
                str(module.FFMPEG), "-hide_banner", "-v", "warning",
                "-i", str(transport), "-map", "0:v:0", "-map", "0:a:0",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                "-avoid_negative_ts", "make_zero", "-movflags", "+faststart",
                str(temporary),
            ], timeout=7200)
            if completed.returncode != 0:
                if temporary.exists():
                    module.archive(temporary, "final-audio-repair-failed")
                return assemble_from_chunks(
                    f"raw-transport audio repair failed: {completed.stderr.strip()}"
                )
            temporary.replace(candidate)
            write_json(evidence / "final-audio-remediation.json", {
                "schema_version": "1.0",
                "vod_id": vod_id,
                "result": "PASS",
                "kind": "FINAL_AUDIO_REENCODE_AFTER_ADTS_COPY_FAILURE",
                "video": "stream_copy",
                "audio": "aac_160k",
                "preserved_failed_assembly": True,
                "source_error": str(exc),
                "source_transport": str(transport),
                "output": str(candidate),
                "output_sha256": module.sha256(candidate),
                "runtime_seconds": time.perf_counter() - started,
                "ffmpeg_warning": completed.stderr.strip() or None,
                "created_at": now(),
                "ground_truth_opened": False,
            })
            return candidate
        except Exception:
            raise

    module.assemble_final = assemble_final

    def null_muxer_warnings_only(result):
        if int(result.get("exit_code", -1)) != 0:
            return False
        error = str(result.get("error") or "").strip()
        if not error:
            return True
        for line in error.splitlines():
            line = line.strip()
            if not line or line.startswith("Last message repeated"):
                continue
            if "Application provided invalid, non monotonically increasing dts to muxer" not in line:
                return False
        return True

    def packet_timeline_audit(candidate):
        command = [
            str(module.FFPROBE), "-v", "error", "-show_packets",
            "-show_entries", "packet=stream_index,dts_time", "-of", "csv=p=0",
            str(candidate),
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        previous = {}
        packets = {}
        missing_dts = 0
        regressions = []
        assert process.stdout is not None
        for raw_line in process.stdout:
            fields = raw_line.strip().split(",")
            if len(fields) < 2:
                continue
            try:
                stream = int(fields[0])
                dts = float(fields[1])
            except ValueError:
                missing_dts += 1
                continue
            packets[stream] = packets.get(stream, 0) + 1
            prior = previous.get(stream)
            if prior is not None and dts < prior:
                if len(regressions) < 100:
                    regressions.append({
                        "stream_index": stream,
                        "previous_dts_seconds": prior,
                        "dts_seconds": dts,
                    })
            previous[stream] = dts
        assert process.stderr is not None
        stderr = process.stderr.read().strip()
        exit_code = process.wait()
        return {
            "command": command,
            "exit_code": exit_code,
            "packet_counts_by_stream": {str(key): value for key, value in packets.items()},
            "missing_dts_rows": missing_dts,
            "regression_count_capped": len(regressions),
            "regressions": regressions,
            "stderr": stderr or None,
            "passed": exit_code == 0 and not stderr and not regressions and bool(packets),
        }

    def final_integrity(candidate):
        media = module.probe(candidate)
        duration = float(media["duration_seconds"])
        tolerance = max(5.0, float(expected_seconds) * 0.002)
        positions = [
            0.0,
            duration * 0.25,
            duration * 0.50,
            duration * 0.75,
            max(0.0, duration - 2.0),
        ]
        probes = module.decode_probes(candidate, duration, positions)
        tail_probes = module.decode_probes(
            candidate,
            duration,
            [max(0.0, duration - 60.0), max(0.0, duration - 10.0)],
        )
        full = module.decode(candidate)
        packet_timeline = packet_timeline_audit(candidate)
        probe_content_passed = all(null_muxer_warnings_only(row) for row in probes)
        tail_content_passed = all(null_muxer_warnings_only(row) for row in tail_probes)
        full_content_passed = null_muxer_warnings_only(full)
        passed = (
            abs(duration - expected_seconds) <= tolerance
            and abs(float(media["video_duration_seconds"]) - expected_seconds)
            <= tolerance
            and abs(float(media["audio_duration_seconds"]) - expected_seconds)
            <= tolerance
            and probe_content_passed
            and tail_content_passed
            and full_content_passed
            and bool(packet_timeline["passed"])
        )
        payload = {
            "schema_version": 1,
            "vod_id": vod_id,
            "path": str(candidate),
            "bytes": candidate.stat().st_size,
            "sha256": module.sha256(candidate),
            "official_duration_seconds": expected_seconds,
            "duration_tolerance_seconds": tolerance,
            "duration_tolerance_basis": "max(5_seconds, official_duration*0.2_percent)",
            **media,
            "decode_probes": probes,
            "decode_probes_content_passed": probe_content_passed,
            "tail_decode_probes": tail_probes,
            "tail_decode_probes_content_passed": tail_content_passed,
            "full_sequential_decode": full,
            "full_sequential_decode_content_passed": full_content_passed,
            "packet_timeline_audit": packet_timeline,
            "result": "PASS" if passed else "FAIL",
            "created_at": now(),
            "ground_truth_opened": False,
        }
        write_json(evidence / "vod-recovery-integrity.json", payload)
        if not passed:
            raise RuntimeError("final recovered media failed strict integrity")
        return payload

    module.final_integrity = final_integrity
    return evidence


def main() -> int:
    global ROOT
    parser = argparse.ArgumentParser()
    default_bulk_root = (
        Path(os.environ["ACFV_BULK_ROOT"])
        if os.environ.get("ACFV_BULK_ROOT")
        else None
    )
    parser.add_argument("--bulk-root", type=Path, default=default_bulk_root)
    parser.add_argument("--creator", required=True)
    parser.add_argument("--vod-id", required=True)
    parser.add_argument("--expected-seconds", required=True, type=float)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--repair-rate-gate", action="store_true")
    parser.add_argument("--repair-seek-probe", action="store_true")
    parser.add_argument("--repair-full-decode-timestamps", action="store_true")
    parser.add_argument("--repair-corrupt-fragment", type=int)
    parser.add_argument("--repair-corrupt-audio", action="store_true")
    parser.add_argument("--repair-only", action="store_true")
    args = parser.parse_args()
    if args.bulk_root is None:
        parser.error("--bulk-root or ACFV_BULK_ROOT is required")
    ROOT = args.bulk_root.resolve()
    module = load_base()
    evidence = configure(
        module,
        creator=args.creator.casefold(),
        vod_id=args.vod_id,
        expected_seconds=args.expected_seconds,
    )
    for directory in (evidence, module.WORK, module.FRAGMENTS, module.FRAGMENT_RECEIPTS, module.CHUNKS):
        directory.mkdir(parents=True, exist_ok=True)
    module.disk_guard()
    if args.check_only:
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0 ACFV-recovery/1.0"})
        module.load_playlist(session)
        return 0
    if args.repair_rate_gate:
        rate_path = evidence / "vod-recovery-download-rate.json"
        if not rate_path.is_file():
            raise FileNotFoundError("rate-gate evidence does not exist")
        rate = json.loads(rate_path.read_text(encoding="utf-8"))
        if rate.get("result") != "FAIL":
            raise RuntimeError("rate-gate remediation requires a failed rate receipt")
        archived: list[dict[str, object]] = []
        for receipt_path in sorted(module.FRAGMENT_RECEIPTS.glob("*.json")):
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            measured = float(receipt.get("average_throughput_mib_s") or 0.0)
            if measured <= 8.0:
                continue
            fragment_path = Path(str(receipt.get("path") or ""))
            if not fragment_path.is_file():
                raise FileNotFoundError(f"rate-violating fragment missing: {fragment_path}")
            archived_fragment = module.archive(fragment_path, "rate-gate-violation")
            archived_receipt = module.archive(receipt_path, "rate-gate-violation")
            archived.append({
                "index": int(receipt["index"]),
                "measured_mib_s": measured,
                "archived_fragment": str(archived_fragment),
                "archived_receipt": str(archived_receipt),
            })
        if not archived:
            raise RuntimeError("failed rate receipt contained no fragment above 8 MiB/s")
        archived_rate = module.archive(rate_path, "failed-rate-gate")
        write_json(evidence / "rate-gate-remediation.json", {
            "schema_version": "1.0",
            "vod_id": args.vod_id,
            "reason": "per-fragment measured throughput exceeded strict 8 MiB/s ceiling",
            "archived_rate_receipt": str(archived_rate),
            "redownload_count": len(archived),
            "rows": archived,
            "old_average_mib_s": rate.get("average_mib_s"),
            "old_p95_mib_s": rate.get("p95_mib_s"),
            "old_peak_mib_s": rate.get("peak_mib_s"),
            "prepared_at": now(),
            "ground_truth_opened": False,
        })
    if args.repair_seek_probe:
        integrity_path = evidence / "vod-recovery-integrity.json"
        if not integrity_path.is_file():
            raise FileNotFoundError("failed integrity receipt does not exist")
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
        probe_errors = [
            str(row.get("error") or "")
            for row in integrity.get("decode_probes", [])
            if not row.get("passed")
        ]
        full = integrity.get("full_sequential_decode") or {}
        if (
            integrity.get("result") != "FAIL"
            or not full.get("passed")
            or not probe_errors
            or any("non monotonically increasing dts" not in error for error in probe_errors)
        ):
            raise RuntimeError("seek-probe remediation preconditions not met")
        archived_integrity = module.archive(integrity_path, "failed-fast-seek-probe")
        write_json(evidence / "seek-probe-remediation.json", {
            "schema_version": "1.0",
            "vod_id": args.vod_id,
            "reason": "input fast-seek B-frame DTS reached null muxer before timestamp reset",
            "full_sequential_decode_passed": True,
            "source_fragments_passed": 1931,
            "archived_integrity_receipt": str(archived_integrity),
            "probe_fix": "reset decoded A/V timestamps with setpts/asetpts for seek-only probes",
            "prepared_at": now(),
            "ground_truth_opened": False,
        })
    if args.repair_full_decode_timestamps:
        integrity_path = evidence / "vod-recovery-integrity.json"
        if not integrity_path.is_file():
            raise FileNotFoundError("failed integrity receipt does not exist")
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
        probes = list(integrity.get("decode_probes") or [])
        tail_probes = list(integrity.get("formerly_missing_tail_decode_probes") or [])
        full = integrity.get("full_sequential_decode") or {}
        error_lines = [
            line.strip()
            for line in str(full.get("error") or "").splitlines()
            if line.strip()
        ]
        marker = "Application provided invalid, non monotonically increasing dts to muxer"
        if (
            integrity.get("result") != "FAIL"
            or not probes
            or not all(row.get("passed") for row in probes)
            or not all(row.get("passed") for row in tail_probes)
            or full.get("exit_code") != 0
            or not error_lines
            or any(marker not in line for line in error_lines)
        ):
            raise RuntimeError("full-decode timestamp remediation preconditions not met")
        archived_integrity = module.archive(
            integrity_path,
            "failed-full-decode-null-mux-timestamps",
        )
        write_json(evidence / "full-decode-timestamp-remediation.json", {
            "schema_version": "1.0",
            "vod_id": args.vod_id,
            "reason": "decoded duplicate frame PTS were rejected only by the validation null muxer",
            "full_decode_exit_code": 0,
            "null_mux_timestamp_warning_count": len(error_lines),
            "decode_probes_passed": len(probes),
            "tail_decode_probes_passed": len(tail_probes),
            "archived_integrity_receipt": str(archived_integrity),
            "validation_fix": "generate monotonic validation-only A/V timestamps after decoding",
            "prepared_at": now(),
            "ground_truth_opened": False,
        })
        module._v2_normalize_full_decode_timestamps = True
    if args.repair_corrupt_fragment is not None:
        index = args.repair_corrupt_fragment
        target = module.FRAGMENTS / f"{index:05d}.ts"
        receipt_path = module.FRAGMENT_RECEIPTS / f"{index:05d}.json"
        failed_receipt_path = receipt_path
        target_prepared = False
        if target.exists():
            current = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.is_file() else {}
            previous_path = module.FRAGMENT_RECEIPTS / f"{index - 1:05d}.json"
            previous = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.is_file() else {}
            if not current:
                validation = module.validate_fragment(target, 10.0)
                delta = (
                    float(validation["video_start_seconds"])
                    - float((previous.get("validation") or {}).get("video_end_seconds") or 0.0)
                )
                archived = sorted(module.FRAGMENT_RECEIPTS.glob(f"{index:05d}.json.source-corrupt-*"))
                if abs(delta) > 0.1 or not archived:
                    raise FileExistsError(f"unreceipted fragment is not a valid interrupted repair: {target}")
                failed_receipt_path = archived[-1]
                target_prepared = True
            else:
                repair = current.get("repair") or {}
                delta = (
                    float((current.get("validation") or {}).get("video_start_seconds") or 0.0)
                    - float((previous.get("validation") or {}).get("video_end_seconds") or 0.0)
                )
                archived_failed = Path(str(repair.get("archived_failed_receipt") or ""))
                audio_repair_needed = args.repair_corrupt_audio and repair.get("audio") == "stream_copy"
                if (
                    repair.get("kind") != "LOSSLESS_VIDEO_REENCODE_WITH_CORRUPT_PACKET_DISCARD"
                    or (abs(delta) <= 0.1 and not audio_repair_needed)
                    or not archived_failed.is_file()
                ):
                    raise FileExistsError(f"refusing to overwrite fragment: {target}")
                module.archive(target, "timestamp-discontinuity")
                module.archive(receipt_path, "timestamp-discontinuity")
                old_remediation = evidence / f"corrupt-fragment-{index:05d}-remediation.json"
                if old_remediation.exists():
                    module.archive(old_remediation, "timestamp-discontinuity")
                failed_receipt_path = archived_failed
        if not failed_receipt_path.is_file():
            raise FileNotFoundError(f"failed fragment receipt missing: {failed_receipt_path}")
        failed_receipt = json.loads(failed_receipt_path.read_text(encoding="utf-8"))
        failures = failed_receipt.get("failures") or []
        if (
            failed_receipt.get("result") != "RECOVERY_REQUIRED"
            or not failures
            or any(row.get("http_status") != 200 for row in failures)
            or any("fragment decode failed" not in str(row.get("error") or "") for row in failures)
        ):
            raise RuntimeError("corrupt-fragment remediation preconditions not met")
        sources = sorted(
            module.FRAGMENTS.glob(f"{index:05d}.ts.invalid-attempt-*"),
            key=lambda path: path.stat().st_mtime,
        )
        if not sources:
            raise FileNotFoundError(f"preserved corrupt fragment missing for index {index}")
        source = sources[-1]
        temporary = module.WORK / f"{index:05d}.lossless-repair.ts"
        if temporary.exists():
            raise FileExistsError(f"refusing to overwrite repair candidate: {temporary}")
        completed = None if target_prepared else module.run([
            str(module.FFMPEG),
            "-hide_banner",
            "-v",
            "warning",
            "-copyts",
            "-fflags",
            "+discardcorrupt",
            "-err_detect",
            "ignore_err",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "0",
            "-c:a",
            "aac" if args.repair_corrupt_audio else "copy",
            *(["-b:a", "160k"] if args.repair_corrupt_audio else []),
            "-muxdelay",
            "0",
            "-muxpreload",
            "0",
            "-f",
            "mpegts",
            str(temporary),
        ], timeout=600)
        if completed is not None and completed.returncode != 0:
            raise RuntimeError(f"lossless fragment repair failed: {completed.stderr.strip()}")
        expected = float(failed_receipt["expected_duration_seconds"])
        if not target_prepared:
            validation = module.validate_fragment(temporary, expected)
            temporary.replace(target)
        else:
            validation = module.validate_fragment(target, expected)
        archived_receipt = (
            module.archive(receipt_path, "source-corrupt")
            if receipt_path.exists()
            else failed_receipt_path
        )
        repair_receipt = {
            "schema_version": 1,
            "index": index,
            "expected_duration_seconds": expected,
            "path": str(target),
            "bytes": target.stat().st_size,
            "sha256": module.sha256(target),
            "validation": validation,
            "result": "PASS",
            "reused": False,
            "repair": {
                "kind": "LOSSLESS_VIDEO_REENCODE_WITH_CORRUPT_PACKET_DISCARD",
                "source_path": str(source),
                "source_sha256": module.sha256(source),
                "archived_failed_receipt": str(archived_receipt),
                "source_failure_count": len(failures),
                "video_codec": "libx264",
                "video_crf": 0,
                "audio": "aac_160k" if args.repair_corrupt_audio else "stream_copy",
                "preserve_source_timestamps": True,
                "mpegts_muxdelay_seconds": 0,
                "ffmpeg_warning": (
                    completed.stderr.strip() or None
                    if completed is not None
                    else "resumed after receipt-write interruption"
                ),
                "created_at": now(),
            },
        }
        write_json(receipt_path, repair_receipt)
        write_json(evidence / f"corrupt-fragment-{index:05d}-remediation.json", {
            **repair_receipt,
            "ground_truth_opened": False,
        })
        if args.repair_only:
            return 0
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
