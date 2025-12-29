from __future__ import annotations

from acfv.modular.contracts import ART_CHAT_LOG, ART_CHAT_SOURCE
from acfv.modular.types import ModuleSpec

from .step import run


spec = ModuleSpec(
    name="extract_chat",
    version="1",
    inputs=[ART_CHAT_SOURCE],
    outputs=[ART_CHAT_LOG],
    run=run,
    description="Parse chat source into normalized chat log JSON.",
    impl_path="src/acfv/steps/extract_chat/step.py",
)

__all__ = ["spec"]
