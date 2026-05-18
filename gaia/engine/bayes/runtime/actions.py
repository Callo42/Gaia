"""Bayes runtime action shapes - Model and ModelComparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gaia.engine.lang.runtime.action import Reasoning
from gaia.engine.lang.runtime.distribution import Distribution
from gaia.engine.lang.runtime.knowledge import Claim
from gaia.engine.lang.runtime.variable import Variable


@dataclass
class BayesInference(Reasoning):
    """Bayes-family reasoning record (marker base class)."""


@dataclass
class Model(BayesInference):
    """Predictive model: ties a hypothesis to a distribution over an observable."""

    hypothesis: Claim | None = None
    observable: Variable | None = None
    distribution: Distribution | None = None
    helper: Claim | None = None


@dataclass
class ModelComparison(BayesInference):
    """Equal-positioned list of competing predictive models."""

    helper: Claim | None = None
    models: tuple[Claim, ...] = ()
    data: tuple[Claim, ...] = ()
    exclusivity: str = "pairwise_contradiction"
    precomputed: Any | None = None
    log_likelihoods: dict[Claim, float] = field(default_factory=dict)
