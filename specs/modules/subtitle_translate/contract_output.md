# Subtitle Translate Contract Output

## Files
- `work/streamer.zh.srt`
- `work/streamer.zh.ass`
- `work/streamer.bilingual.ass` (optional)
- `work/translation_cache.jsonl`

## Payload
```
{
  "status": "ok|disabled|missing_source|empty",
  "source": "path/to/subtitles_streamer.ass",
  "zh_srt": "path/to/streamer.zh.srt",
  "zh_ass": "path/to/streamer.zh.ass",
  "bilingual_ass": "path/to/streamer.bilingual.ass",
  "cache_path": "path/to/translation_cache.jsonl",
  "count": 123,
  "engine": "llm_json"
}
```
