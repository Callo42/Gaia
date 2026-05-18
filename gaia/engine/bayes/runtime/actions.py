"""Bayes runtime action shapes — Prediction and ModelComparison."""

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
class Prediction(BayesInference):
    """Predictive model: ties a hypothesis to a distribution over a target.

    ``target`` is the random variable whose value is predicted under
    ``hypothesis``; it can be a :class:`Variable` (the discrete-count
    Bayes style) or a :class:`Distribution` Knowledge node (predict on
    top of an already-declared random variable).
    """

    hypothesis: Claim | None = None
    target: Variable | Distribution | None = None
    distribution: Distribution | None = None
    helper: Claim | None = None


@dataclass
class ModelComparison(BayesInference):
    """Equal-positioned list of competing predictive models.

    ``models`` carries the helper Claims returned by :func:`predict`
    (one per hypothesis). ``data`` are the observation Claims to
    evaluate. The lowering binds each model's distribution to its
    hypothesis' parameter values, computes a log-likelihood, and emits
    one ``infer`` strategy per hypothesis.
    """

    helper: Claim | None = None
    models: tuple[Claim, ...] = ()
    data: tuple[Claim, ...] = ()
    exclusivity: str = "pairwise_contradiction"
    precomputed: Any | None = None
    log_likelihoods: dict[Claim, float] = field(default_factory=dict)
