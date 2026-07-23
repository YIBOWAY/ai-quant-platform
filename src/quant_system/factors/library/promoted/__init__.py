"""Code-reviewed, promoted factor library (Gate-3 output of D-20).

Each module under this package holds exactly one human-reviewed, git-committed
factor promoted from an approved candidate. This file is REGENERATED
deterministically by ``quant-system agent promote-candidate`` (sorted imports) -- do not
edit by hand. ``PROMOTED_FACTORS`` is the single source the registry factory
reads. It starts empty; promotions append.
"""

from __future__ import annotations

from quant_system.factors.base import BaseFactor
from quant_system.factors.library.promoted import (
    agent_candidate_wave2_sceneb_mom20_v3 as agent_candidate_wave2_sceneb_mom20_v3_module,
)
from quant_system.factors.library.promoted import (
    paper_reversal_momentum_proxy_v2 as paper_reversal_momentum_proxy_v2_module,
)

PROMOTED_FACTORS: tuple[type[BaseFactor], ...] = (
    agent_candidate_wave2_sceneb_mom20_v3_module.AgentCandidateFactor,
    paper_reversal_momentum_proxy_v2_module.PaperReversalMomentumProxyV2,
)

__all__ = ["PROMOTED_FACTORS"]
