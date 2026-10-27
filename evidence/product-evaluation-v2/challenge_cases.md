# CHALLENGE SET

These 15 cases are selected from the normal evaluation cases and are not counted as an additional random sample.

## Retrieval

- `R01` — target rank `NOT FOUND`; style `zh`; query: 哪一段把某个恐怖游戏描述成会用人的思想和实体沟通？
- `R02` — target rank `NOT FOUND`; style `zh`; query: 她饿了却为什么还是不愿意走出房间？
- `R03` — target rank `NOT FOUND`; style `zh`; query: 结局附近她认出 Rebecca 时说了什么？
- `R04` — target rank `NOT FOUND`; style `zh`; query: 哪段像在做天气播报，先说外面很晴朗后来又说多云？
- `R05` — target rank `NOT FOUND`; style `zh`; query: 她什么时候反思自己可能把一些分类看得太轻了？

## Moments

- `M07` — `AUTO_SUSPECT`; duration `5.000s`; reasons `duplicate_transcript, low_summary_lexical_grounding`
- `M10` — `AUTO_SUSPECT`; duration `5.000s`; reasons `duplicate_transcript, low_summary_lexical_grounding`
- `M13` — `AUTO_SUSPECT`; duration `2.000s`; reasons `unusually_short, duplicate_transcript`
- `M25` — `AUTO_SUSPECT`; duration `2.000s`; reasons `unusually_short`
- `M15` — `AUTO_PASS`; duration `5.000s`; reasons `lowest grounding/extreme duration among remaining cases`

## Clips

- `CL14` — `AUTO_SUSPECT`; silence `0.271782`; reasons `ends_mid_transcript_segment`
- `CL11` — `AUTO_SUSPECT`; silence `0.069411`; reasons `starts_mid_transcript_segment`
- `CL05` — `AUTO_SUSPECT`; silence `0.016608`; reasons `ends_mid_transcript_segment`
- `CL08` — `AUTO_SUSPECT`; silence `0.01494`; reasons `ends_mid_transcript_segment`
- `CL01` — `AUTO_SUSPECT`; silence `0.0`; reasons `starts_mid_transcript_segment, ends_mid_transcript_segment`
