from __future__ import annotations

from acfv.modular.types import ModuleSpec

from .step import CHAT_TYPE, OUT_TYPE, run


spec = ModuleSpec(
    name="chat_spike",
    version="0.1",
    inputs=[CHAT_TYPE],
    outputs=[OUT_TYPE],
    run=run,
    description="Find chat activity spikes and emit segment candidates.",
    impl_path="src/acfv/steps/chat_spike/step.py",
    default_params={"window_sec": 20.0, "top_n": 5},
)

__all__ = ["spec"]
