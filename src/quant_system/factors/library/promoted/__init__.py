"""Code-reviewed, promoted factor library (Gate-3 output of D-20).

Each module under this package holds exactly one human-reviewed, git-committed
factor promoted from an approved candidate. ``PROMOTED_FACTORS`` is regenerated
deterministically by ``agent promote-candidate`` (sorted imports) and is the
single source the registry factory reads. It starts empty; promotions append.
"""

from __future__ import annotations

from quant_system.factors.base import BaseFactor

PROMOTED_FACTORS: tuple[type[BaseFactor], ...] = ()

__all__ = ["PROMOTED_FACTORS"]
