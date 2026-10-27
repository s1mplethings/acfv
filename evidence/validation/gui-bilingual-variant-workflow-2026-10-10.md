# 1. Repository

branch: `feature/gui-bilingual-variant-workflow`
base: `59dc77be7b9f5537271f6baf0e9f596e5c301395`
implementation head: `296be92f86edb9e175a82061c8d63c16a0a845dd`
evidence head: evidence-only commit containing this report
working tree: clean after evidence commit

# 2. GUI Architecture

Review page: formal `ReviewTab` with embedded player, five duration choices, variant comparison, bilingual Cue table and review actions
Controller: `GuiVariantWorkflowService`; durable state beside event outputs
Variant service: canonical `ClipVariantService`, called once per profile with independent stages/failure state
Subtitle service: canonical `BilingualSubtitleService` for load, validation, edited-track persistence and artifact rebuild
Persistence: GUI workflow JSON + edited track/revision manifests; Library Clip/Feedback is updated when the Event Plan owns a persisted Clip
Player: existing PyQt5 Multimedia, stopped at 0 by default; Play/Pause/Seek/Time/Volume/Replay available

# 3. Duration Workflow

Short: real 32.600s READY
Standard: real 67.400s READY; default
Long: real 84.420s READY
Full Event: real 87.360s READY
Custom: 5–600s target/min/max with canonical duration conflict handling
Generate Selected: background QThread → workflow → canonical variant service
Generate All: four independent serial service calls, cancel-before-next, completed variants retained

# 4. Variant Comparison

list: Profile, duration, boundaries, Hook/Setup/Payoff/Reaction/Aftermath, cue count, status, actions
status: NOT_GENERATED through READY/FAILED/INTERRUPTED/RETRY_AVAILABLE with generation phases
preview: each READY row loads its latest bilingual MP4 without autoplay
selection: Select action updates highlight, latest output and selected timestamp
similarity warning: LONG/FULL_EVENT under five seconds apart displays the required message
persistence: selection/settings/revisions survive service and GUI restart

# 5. Subtitle Editor

Chinese edit: editable table column; real STANDARD cue edited
English edit: editable table column; same cue edited
save: canonical subtitle service validation → `bilingual_track.edited.json`
validation: empty language and embedded line break block save; CPS warnings remain visible
restart persistence: PASS
dirty state: per-variant flag, edit count/status and regeneration preserve/reset choice

# 6. Re-render

selected variant: STANDARD
revision: `revision_001`
old hash: `72BB2D05F2069314D24977B6AC3358CCC7C93839F5E515DF1C7D1924658531C0`
new hash: `BF220CFE62270A197BA618554E38361351B58B5D1043360E45007BD227359954`
ffprobe: PASS, H.264/AAC, 1920×1080, 67.433s
decode: PASS, zero decode errors

# 7. Review / Feedback

Accept: persisted as ACCEPTED with profile/output/boundaries/display mode/edit count/revision/timestamp
Reject: reason selector supports the eight required categories and persists the choice
selected variant persistence: PASS
feedback: canonical FeedbackService used when plan Clip exists; event artifact review state remains durable for plan-only validation

# 8. GUI Deep Link

command: `python -m acfv.cli gui --open-recording 121a99a3-affb-4e74-80de-c5fd13ed7c4b --open-review --event-plan <plan> --output-root <recording-output>`
Recording: `121a99a3-affb-4e74-80de-c5fd13ed7c4b`
page: formal MainWindow Review tab
default variant: STANDARD
loaded media: selected STANDARD revision, stopped at 0

# 9. Native GUI Handoff

GUI PID: 40600
window title: 视频处理工具 - 模块化版本
process alive: YES
video opened: YES, VLC PID 38016
Explorer opened: YES, PID 13624
left running for user: YES; persistent launcher session remains active

# 10. Actual Output

Short: `final_clip_short_bilingual.mp4`, 32.600s
Standard: `standard/revisions/revision_001/clip_bilingual.mp4`, 67.400s semantic boundary / 67.433s media
Long: `final_clip_long_bilingual.mp4`, 84.420s
Full Event: `final_clip_full_event_bilingual.mp4`, 87.360s
selected final video: STANDARD revision 001
selected profile: STANDARD
selected duration: 67.400s

# 11. Automated Tests

compileall: PASS ×2
CLI: all five requested help commands PASS ×2
pytest #1: 360 passed, 11 warnings
pytest #2: 360 passed, 11 warnings
coverage: focused aggregate 74%; new workflow 86%, variant 88%, Clip/Subtitle services 82%, Review widget 66%
verify: PASS ×2
contracts: PASS ×2

# 12. Real GUI Smoke

window visible: YES, non-zero native handle
Review visible: YES by synchronous deep-link routing before MainWindow show
variants visible: YES by real state recovery plus Qt widget integration test
Standard selected: YES
Cue table visible: YES; 12 STANDARD cues loaded by integration test
video loaded: YES; selected revision path and VLC window verified
errors: no fallback window and no blocking startup dialog; native Computer Use inventory was unavailable for independent screenshot capture

# 13. Bugs Fixed

| ID | Severity | Observed Failure | Root Cause | General Fix | Regression | Commit |
|---|---|---|---|---|---|---|
| GUI-001 | Critical | Generate All checkbox did not generate | no workflow adapter | durable service calling ClipVariantService | Generate All unit + two real revisions | 296be92 |
| GUI-002 | High | Cue editors were disconnected | no track-level persistence | canonical edited track API + validation | restart/rerender test + real edit | 296be92 |
| GUI-003 | High | rerender overwrote/no revision history | single output path | revision_NNN, hashes and media receipt | real revision_001 | 296be92 |
| GUI-004 | High | selection only existed in controls | no durable selected output | workflow state + ClipService selected variant API | restart persistence | 296be92 |
| GUI-005 | High | no direct Review startup | CLI discarded context | normal MainWindow deep link | CLI/app tests + native launch | 296be92 |
| GUI-006 | High | VALIDATING could precede real decode | media scan external to GUI workflow | integrated ffprobe/full decode before READY | real revision-002 | 296be92 |

# 14. Regression

Retrieval: full suite PASS
Conversation: full suite PASS
Moment: full suite PASS
Watchability: full suite PASS
Clip: full suite and real render PASS
Download: full suite/CLI smoke PASS
Live: full suite/CLI smoke PASS
Feedback: persistence tests PASS
CGNK: capability registry, repository guards and contract checks PASS; CGNK Provider formal evidence remains NOT_EVALUATED because the Provider MCP tools were unavailable

# 15. Human Review

review sheet: `outputs/bilingual-duration-validation/121a99a3-affb-4e74-80de-c5fd13ed7c4b/final-gui-human-review.md`
status: OPEN_FOR_USER_REVIEW
GUI/video left open: YES

# 16. Remaining Problems

- The host Computer Use connector returned no native app inventory, so native visibility was verified through Windows process/window handles and Qt integration state rather than an independent screenshot.
- Review widget focused coverage is 66% because native multimedia/dialog branches are not all exercised automatically; the canonical workflow service is 86% and two full 360-test rounds pass.
- Several untouched Argos-translated cues remain literal and should be judged in the open human review; the first STANDARD cue was manually improved and revisioned.

# 17. Engineering Status

GUI_GENERATE_ALL_READY: YES
GUI_VARIANT_COMPARISON_READY: YES
GUI_BILINGUAL_CUE_EDITOR_READY: YES
GUI_RERENDER_READY: YES
GUI_FINAL_SELECTION_READY: YES
GUI_DEEP_LINK_READY: YES
NATIVE_GUI_OPENED_FOR_USER: YES
FINAL_VIDEO_OPENED_FOR_USER: YES
FULL_GUI_PRODUCT_WORKFLOW_READY: YES
