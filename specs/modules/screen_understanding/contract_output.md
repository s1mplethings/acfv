# Screen Understanding 输出契约

- `schema_version`: 当前为 `1.0.0`。
- `status`: `ok/disabled/video_open_failed/cv2_unavailable`。
- `timeline`: `[{start,end,screen_type,app_guess,activity,entities,summary,confidence,...}]`

确定性要求：
- timeline 必须按 `start` 升序。
- 同一输入与同一抽帧配置下，关键帧落盘命名稳定。
