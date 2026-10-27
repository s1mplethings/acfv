"""Persistent moments built from canonical pipeline evidence."""

from .builder import MomentDraft, ProvisionalMomentBuilder
from .models import Moment, MomentStatus
from .quality import MomentQualityAction, MomentQualityDecision, classify_moments, repair_moments

__all__ = ["Moment", "MomentDraft", "MomentFinalizer", "MomentQualityAction", "MomentQualityDecision", "MomentService", "MomentStatus", "ProvisionalMomentBuilder", "classify_moments", "repair_moments"]


def __getattr__(name: str):
    if name == "MomentFinalizer":
        from .finalize import MomentFinalizer

        return MomentFinalizer
    if name == "MomentService":
        from .service import MomentService

        return MomentService
    raise AttributeError(name)
