# Twitch VOD Download

- Purpose: turn one existing Twitch VOD URL into trusted local media and a durable
  Creator Library Recording before submitting it to the canonical processing pipeline.
- Canonical Interface: `acfv.library.vod_download.VodDownloadService`.
- Implementation: lifecycle and persistence live in `src/acfv/library/vod_download.py`;
  `src/acfv/providers/download.py` is the thin TwitchDownloaderCLI process adapter.
- Inputs: Twitch `/videos/<id>` URL or numeric ID, optional start/end offsets, provider
  configuration, and an optional cancellation event.
- Outputs: deduplicated Creator/Source/Recording/VodDownload rows, canonical local MP4,
  media validation metadata, progress, and the existing backend processing job.
- Effects: writes temporary and completed media only under canonical runtime Library
  storage; validated media is atomically promoted before processing starts.
- Errors: invalid/channel/non-Twitch inputs create no rows; deleted/private VODs,
  provider/network failures, interruption, invalid media, and probe failure become
  explicit durable states. Partial media is retained and never processed.
- Success semantics: provider exit code 0 means only `TRANSFER_COMPLETED`. The durable
  lifecycle must then enter `MEDIA_INTEGRITY_VALIDATION`; only a passing independent
  stream/duration/decode check may produce `DOWNLOAD_READY` and `INGEST_READY`.
  Validation failure is recorded as `INCOMPLETE_MEDIA` / `RECOVERY_REQUIRED`, retains
  the partial media and measured validation payload, and never hands it to Library
  processing.
- Storage safety: TwitchDownloaderCLI receives an explicit temporary directory beside
  the target Recording. This prevents its implicit cache drive from filling a different
  volume and makes the download/merge disk budget observable as one unit.
- Bulk corpus safety: bulk acquisition uses `acfv.runtime.bulk_storage.select_bulk_storage`.
  Q is preferred only when it is a healthy non-system volume with sufficient capacity;
  otherwise a healthy large local HDD may be selected. The post-download free-space
  reserve is `max(15% capacity, 200 GiB)`. If no volume satisfies it, formal bulk
  acquisition fails closed as `BULK_STORAGE_NOT_AVAILABLE`; small bounded probes may
  still run. Persisted locators use `BULK_MEDIA_ROOT/...`, never a machine-specific path.
- Dependencies: Creator Library, TwitchDownloaderCLI adapter, FFmpeg/ffprobe, and
  `LibraryService.process_recording` for the only processing handoff.
- Acceptance: platform + external VOD ID is unique; concurrent duplicate submissions
  produce one job; completion requires video+audio, duration, decode and silence scans;
  restart converts in-flight state to `INTERRUPTED`; unsupported byte resume is reported
  as `SAFE_RESTART_ONLY`; exit 0 with incomplete media fails closed and remains
  recoverable; GUI and CLI read the same durable state.
- Retry semantics: a `FAILED` or `INTERRUPTED` range job may be retried with a revised
  explicit range on the same unique VOD row. The repository resets it to `DISCOVERED`
  and updates range provenance; it never creates a duplicate Source/Recording.

The three ingestion modes remain distinct adapters: `LIVE_CAPTURE`, `VOD_DOWNLOAD`, and
`LOCAL_IMPORT`. All three converge on the existing canonical processing pipeline.
