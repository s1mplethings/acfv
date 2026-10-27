"""Workflow-oriented ACFV desktop interface.

The package is deliberately a presentation layer.  Domain state and media
operations remain owned by the services in :mod:`acfv.library`,
:mod:`acfv.retrieval`, :mod:`acfv.conversation`, and :mod:`acfv.clips`.
"""

from .shell import ProductMainWindow

__all__ = ["ProductMainWindow"]
