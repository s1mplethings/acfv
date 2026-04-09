# Screen Detect 输出契约

- `schema_version`: 当前为 `1.0.0`
- `frames`: `[{timestamp_sec,frame_path,screen_bbox,is_fullscreen_capture,ocr_text_hint,confidence}]`
- `windows`: `[{start,end,frame_paths,screen_bbox,is_fullscreen_capture,ocr_text_hint,confidence}]`

确定性要求：
- `windows` 按 `start` 升序。
- bbox 使用 `[x1,y1,x2,y2]`。
