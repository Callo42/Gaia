"""gaia.engine.bayes — hypothesis-data inference verbs.

The user-facing surface is three verbs plus one Claim subclass:

* :func:`predict` — declare a predictive distribution for one hypothesis.
* :func:`compare` — compare equal-positioned predictive models against data.
* :class:`PrecomputedLikelihoods` — audit-bearing return type for
  external-solver wrappers (PyMC / Stan / NumPyro / ...). Always pair
  with the standard :func:`gaia.engine.lang.compute` decorator to
  record the wrapper's ``fn`` / ``code_hash`` provenance.

Distributions live at :mod:`gaia.engine.lang` (the same factories that
back the quantity-with-predicate surface). The pydantic
``_BaseDistribution`` types at :mod:`gaia.engine.bayes.distributions` are
internal scipy-backend implementations — they are not part of the
authoring surface.

See ``docs/specs/2026-05-17-bayes-unified-design.md`` for the design,
``docs/foundations/gaia-lang/bayes.md`` for the user-facing tutorial,
and ``scripts/demo_v06_pymc_integration.py`` for an end-to-end PyMC
integration demo.
"""

from __future__ import annotations

from gaia.engine.bayes.compiler import register_bayes_lowerer as _register_bayes_lowerer
from gaia.engine.bayes.dsl.compare import compare
from gaia.engine.bayes.dsl.predict import predict
from gaia.engine.bayes.runtime import (
    BayesInference,
    ModelComparison,
    PrecomputedLikelihoods,
    Prediction,
)
from gaia.engine.lang.runtime.action import Action
from gaia.engine.lang.runtime.roles import RoleAdder, register_role_handler


def _register_bayes_roles() -> None:
    def prediction_roles(action: Action, add: RoleAdder) -> None:
        if not isinstance(action, Prediction):
            return
        add(action.hypothesis, "hypothesis")
        add(action.helper, "model_helper")

    def model_comparison_roles(action: Action, add: RoleAdder) -> None:
        if not isinstance(action, ModelComparison):
            return
        for model_helper in action.models:
            add(model_helper, "compared_model")
        for data_claim in action.data:
            add(data_claim, "likelihood_data")
        add(action.helper, "model_preference_helper")

    register_role_handler(Prediction, prediction_roles)
    register_role_handler(ModelComparison, model_comparison_roles)


_register_bayes_roles()

_register_bayes_lowerer()

__all__ = [
    "BayesInference",
    "ModelComparison",
    "PrecomputedLikelihoods",
    "Prediction",
    "compare",
    "predict",
]
