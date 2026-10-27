# Clip Review

- Purpose: persist human boundary edits and Accept/Reject state for a rendered proposal.
- Canonical Interface: `acfv.clips.service.ClipService.update_review` and
  `acfv.clips.gui_workflow.GuiVariantWorkflowService` for durable multi-variant review artifacts.
- Implementation: `src/acfv/clips/service.py`, `src/acfv/clips/gui_workflow.py`.
- Inputs: Clip ID, review status, optional boundaries/subtitle settings.
- Outputs: updated durable Clip.
- Effects: revision and review fields change; rerender remains explicit.
- Errors: unknown Clip or invalid boundaries fail explicitly.
- Dependencies: Creator Library repository and Clip Rendering for explicit rerender.
- Acceptance: subtitle/boundary edits rerender successfully and review state survives restart.
  The normal Review GUI can load one event plan, recover completed variants, preview/select them,
  save bilingual text edits through `BilingualSubtitleService`, create versioned rerenders through
  `ClipVariantService`, and persist Accept/Reject without direct SQL, subtitle serialization, or
  FFmpeg calls in the widget.
