"""Bayes ``predict`` / ``compare`` runtime actions and compiler lowering."""

from __future__ import annotations

import math

import pytest
import scipy.stats as stats

import gaia.engine.bayes as bayes
from gaia.engine.bayes.runtime import ModelComparison, Prediction
from gaia.engine.bp.exact import exact_inference
from gaia.engine.bp.factor_graph import FactorType
from gaia.engine.bp.lowering import lower_local_graph
from gaia.engine.ir.operator import OperatorType
from gaia.engine.ir.parameterization import CROMWELL_EPS
from gaia.engine.lang import (
    Binomial,
    Nat,
    Normal,
    Probability,
    Real,
    Variable,
    contradict,
    observe,
    parameter,
)
from gaia.engine.lang.compiler.compile import compile_package_artifact
from gaia.engine.lang.runtime.action import Observe
from gaia.engine.lang.runtime.knowledge import _current_package
from gaia.engine.lang.runtime.package import CollectedPackage
from gaia.engine.lang.runtime.roles import roles_for_package


def _compiled_mendel_bayes(
    *,
    exclusivity: str = "exhaustive_pairwise_complement",
    precomputed: dict | None = None,
):
    """Build the canonical Mendel 3:1 vs Null 1:1 comparison."""
    pkg = CollectedPackage(name="bayes_mendel_pkg", namespace="t")
    token = _current_package.set(pkg)
    try:
        theta = Variable(symbol="theta", domain=Probability)
        k = Variable(symbol="k", domain=Nat, value=295)
        n = 395

        h_31 = parameter(theta, 0.75, content="theta = 0.75.", prior=0.5, label="h_3_1")
        h_null = parameter(theta, 0.5, content="theta = 0.5.", prior=0.5, label="h_null")
        data = observe(k, value=295, label="data", rationale="Observed k = 295.")
        model_31 = bayes.predict(
            h_31,
            target=k,
            distribution=Binomial("k under 3:1", n=n, p=theta),
            label="f2_model_3_1",
        )
        model_null = bayes.predict(
            h_null,
            target=k,
            distribution=Binomial("k under null", n=n, p=theta),
            label="f2_model_null",
        )
        cmp_result = bayes.compare(
            data,
            models=[model_31, model_null],
            exclusivity=exclusivity,
            precomputed=precomputed,
            label="f2_likelihood",
        )
    finally:
        _current_package.reset(token)
    return pkg, h_31, h_null, data, model_31, model_null, cmp_result


def test_bayes_module_does_not_extend_factor_or_operator_enums():
    """The unified surface lowers into existing IR / BP primitives."""
    assert not any("bayes" in str(factor_type).lower() for factor_type in FactorType)
    assert not any("bayes" in str(operator_type).lower() for operator_type in OperatorType)


def test_predict_and_compare_are_action_backed_helper_claims():
    pkg, h_31, _h_null, data, model_31, model_null, cmp_result = _compiled_mendel_bayes()

    model_action = model_31.from_actions[0]
    assert isinstance(model_action, Prediction)
    assert model_action.hypothesis is h_31
    assert isinstance(model_action.target, Variable)
    assert model_action.target.symbol == "k"
    assert model_action.helper is model_31
    assert model_31.metadata["helper_kind"] == "predictive_model"
    assert model_31.metadata["prediction"]["kind"] == "prediction"

    cmp_action = cmp_result.from_actions[0]
    assert isinstance(cmp_action, ModelComparison)
    assert cmp_action.models == (model_31, model_null)
    assert cmp_action.data == (data,)
    assert cmp_action.helper is cmp_result
    assert cmp_result.metadata["helper_kind"] == "model_preference"
    assert cmp_result.metadata["comparison"]["kind"] == "comparison"

    assert model_31 in pkg.knowledge
    assert cmp_result in pkg.knowledge
    assert model_action in pkg.actions
    assert cmp_action in pkg.actions

    roles = roles_for_package(pkg)
    assert "hypothesis" in [occ.role for occ in roles[h_31]]
    assert "model_helper" in [occ.role for occ in roles[model_31]]
    assert "compared_model" in [occ.role for occ in roles[model_31]]
    assert "compared_model" in [occ.role for occ in roles[model_null]]
    assert "likelihood_data" in [occ.role for occ in roles[data]]
    assert "model_preference_helper" in [occ.role for occ in roles[cmp_result]]


def test_observe_variable_with_distribution_noise_stores_knowledge_object():
    pkg = CollectedPackage(name="bayes_noise_pkg", namespace="t")
    token = _current_package.set(pkg)
    try:
        k = Variable(symbol="k", domain=Probability, value=0.7)
        noise = Normal("measurement noise", mu=0.0, sigma=0.1)
        obs = observe(k, value=0.7, error=noise, label="obs")
    finally:
        _current_package.reset(token)

    observation = obs.metadata["observation"]
    assert observation["kind"] == "observation"
    assert observation["value"] == 0.7
    assert observation["target"] is k
    assert observation["noise"] is noise


def test_observe_variable_with_scalar_error_sugars_into_anonymous_normal():
    """Scalar error becomes a Distribution Knowledge node, not a dict payload."""
    pkg = CollectedPackage(name="bayes_data_pkg", namespace="t")
    token = _current_package.set(pkg)
    try:
        y = Variable(symbol="log_rr", domain=Real)
        data = observe(y, value=-0.151, error=0.05, label="measured_log_rr")
    finally:
        _current_package.reset(token)

    assert data.label == "measured_log_rr"
    observation = data.metadata["observation"]
    assert observation["target"] is y
    assert observation["value"] == -0.151
    # Noise is always a Distribution Knowledge object — never a dict payload.
    noise = observation["noise"]
    assert isinstance(noise, Normal.__call__.__class__) or noise.kind == "normal"
    assert noise.params["mu"] == 0.0
    assert noise.params["sigma"] == 0.05
    assert data.prior == pytest.approx(1.0 - CROMWELL_EPS)
    assert data in pkg.knowledge

    observe_action = data.from_actions[0]
    assert isinstance(observe_action, Observe)
    assert observe_action.conclusion is data
    assert observe_action.given == ()
    assert observe_action in pkg.actions


def test_compare_compiles_to_reviewable_infer_strategies_and_exhaustive_complement():
    pkg, h_31, h_null, _data, _model_31, _model_null, cmp_result = _compiled_mendel_bayes()
    cmp_result.from_actions[0].precomputed = {h_31: -1.2, h_null: -5.1}
    cmp_result.from_actions[0].log_likelihoods = {h_31: -1.2, h_null: -5.1}

    compiled = compile_package_artifact(pkg)
    graph = compiled.graph
    h_31_id = compiled.knowledge_ids_by_object[id(h_31)]
    h_null_id = compiled.knowledge_ids_by_object[id(h_null)]
    cmp_id = compiled.knowledge_ids_by_object[id(cmp_result)]

    cmp_ir = next(k for k in graph.knowledges if k.id == cmp_id)
    likelihoods = cmp_ir.metadata["comparison"]["likelihoods"]
    assert set(likelihoods) == {h_31_id, h_null_id}
    assert likelihoods[h_31_id] == pytest.approx(-1.2)
    assert likelihoods[h_null_id] == pytest.approx(-5.1)

    infer_strategies = [
        s
        for s in graph.strategies
        if (s.metadata or {}).get("comparison_factor", {}).get("kind") == "comparison_factor"
    ]
    assert len(infer_strategies) == 2
    assert {tuple(s.premises) for s in infer_strategies} == {(h_31_id,), (h_null_id,)}
    assert {s.conclusion for s in infer_strategies} == {cmp_id}
    assert all(
        s.metadata["action_label"] == "t:bayes_mendel_pkg::action::f2_likelihood"
        for s in infer_strategies
    )

    complement_ops = [
        op
        for op in graph.operators
        if op.operator == "complement"
        and (op.metadata or {})
        .get("action_label", "")
        .endswith("::action::f2_likelihood_exclusive_h_3_1_h_null")
    ]
    assert len(complement_ops) == 1
    assert set(complement_ops[0].variables) == {h_31_id, h_null_id}

    manifest_actions = {review.action_label for review in compiled.review.reviews}
    assert "t:bayes_mendel_pkg::action::f2_model_3_1" in manifest_actions
    assert "t:bayes_mendel_pkg::action::f2_model_null" in manifest_actions
    assert "t:bayes_mendel_pkg::action::f2_likelihood" in manifest_actions
    assert "t:bayes_mendel_pkg::action::f2_likelihood_exclusive_h_3_1_h_null" in manifest_actions

    fg = lower_local_graph(graph)
    beliefs, _ = exact_inference(fg)
    odds = beliefs[h_31_id] / beliefs[h_null_id]
    assert odds == pytest.approx(46.942, rel=0.02)
    assert beliefs[h_31_id] > 0.95
    assert beliefs[h_null_id] < 0.03
    assert beliefs[cmp_id] > 0.99


def test_compare_precomputed_uses_hypothesis_claim_keys_not_model_helpers():
    pkg, _h_31, h_null, data, model_31, model_null, _cmp_result = _compiled_mendel_bayes()
    token = _current_package.set(pkg)
    try:
        with pytest.raises(ValueError, match="precomputed likelihood keys"):
            bayes.compare(
                data,
                models=[model_31, model_null],
                precomputed={model_31: -1.0, h_null: -2.0},
                label="bad_cmp",
            )
    finally:
        _current_package.reset(token)


def test_compare_precomputed_requires_every_model_hypothesis():
    pkg, h_31, _h_null, data, model_31, model_null, _cmp_result = _compiled_mendel_bayes()
    token = _current_package.set(pkg)
    try:
        with pytest.raises(ValueError, match="precomputed likelihoods must cover"):
            bayes.compare(
                data,
                models=[model_31, model_null],
                precomputed={h_31: -1.0},
                label="missing_precomputed",
            )
    finally:
        _current_package.reset(token)


def test_compare_precomputed_rejects_non_claim_keys_cleanly():
    pkg, _h_31, _h_null, data, model_31, model_null, _cmp_result = _compiled_mendel_bayes()
    token = _current_package.set(pkg)
    try:
        with pytest.raises(ValueError, match="precomputed likelihood keys"):
            bayes.compare(
                data,
                models=[model_31, model_null],
                precomputed={"h_3_1": -1.0},
                label="bad_key",
            )
    finally:
        _current_package.reset(token)


def test_continuous_normal_noise_likelihood_uses_convolution():
    """Distribution-typed noise on observe() flows through the convolution lowering."""
    pkg = CollectedPackage(name="bayes_noise_pkg", namespace="t")
    token = _current_package.set(pkg)
    try:
        mu = Variable(symbol="mu", domain=Real)
        y = Variable(symbol="y", domain=Real, value=3.0)
        h_near = parameter(mu, 2.5, content="mu = 2.5.", prior=0.5, label="h_near")
        h_far = parameter(mu, 0.0, content="mu = 0.", prior=0.5, label="h_far")
        data = observe(
            y,
            value=3.0,
            error=Normal("measurement noise", mu=0.0, sigma=2.0),
            label="data",
        )
        model_near = bayes.predict(
            h_near,
            target=y,
            distribution=Normal("y under near", mu=mu, sigma=1.0),
            label="model_near",
        )
        model_far = bayes.predict(
            h_far,
            target=y,
            distribution=Normal("y under far", mu=mu, sigma=1.0),
            label="model_far",
        )
        cmp_result = bayes.compare(data, models=[model_near, model_far], label="cmp")
    finally:
        _current_package.reset(token)

    compiled = compile_package_artifact(pkg)
    h_near_id = compiled.knowledge_ids_by_object[id(h_near)]
    h_far_id = compiled.knowledge_ids_by_object[id(h_far)]
    cmp_id = compiled.knowledge_ids_by_object[id(cmp_result)]
    cmp_ir = next(k for k in compiled.graph.knowledges if k.id == cmp_id)

    likelihoods = cmp_ir.metadata["comparison"]["likelihoods"]
    convolved_sigma = math.sqrt(1.0**2 + 2.0**2)
    assert likelihoods[h_near_id] == pytest.approx(
        stats.norm.logpdf(3.0, loc=2.5, scale=convolved_sigma),
        rel=1e-5,
    )
    assert likelihoods[h_far_id] == pytest.approx(
        stats.norm.logpdf(3.0, loc=0.0, scale=convolved_sigma),
        rel=1e-5,
    )


def test_observe_with_scalar_error_consumed_by_compare_lowering():
    """Scalar ``error=σ`` on observe() reaches compare()'s convolution path."""
    pkg = CollectedPackage(name="bayes_data_noise_pkg", namespace="t")
    token = _current_package.set(pkg)
    try:
        mu = Variable(symbol="mu", domain=Real)
        y = Variable(symbol="y", domain=Real)
        h_near = parameter(mu, 2.5, content="mu = 2.5.", prior=0.5, label="h_near")
        h_far = parameter(mu, 0.0, content="mu = 0.", prior=0.5, label="h_far")
        data = observe(y, value=3.0, error=2.0, label="data")
        model_near = bayes.predict(
            h_near,
            target=y,
            distribution=Normal("y under near", mu=mu, sigma=1.0),
            label="model_near",
        )
        model_far = bayes.predict(
            h_far,
            target=y,
            distribution=Normal("y under far", mu=mu, sigma=1.0),
            label="model_far",
        )
        cmp_result = bayes.compare(data, models=[model_near, model_far], label="cmp")
    finally:
        _current_package.reset(token)

    compiled = compile_package_artifact(pkg)
    h_near_id = compiled.knowledge_ids_by_object[id(h_near)]
    h_far_id = compiled.knowledge_ids_by_object[id(h_far)]
    cmp_id = compiled.knowledge_ids_by_object[id(cmp_result)]
    cmp_ir = next(k for k in compiled.graph.knowledges if k.id == cmp_id)

    likelihoods = cmp_ir.metadata["comparison"]["likelihoods"]
    convolved_sigma = math.sqrt(1.0**2 + 2.0**2)
    assert likelihoods[h_near_id] == pytest.approx(
        stats.norm.logpdf(3.0, loc=2.5, scale=convolved_sigma),
        rel=1e-5,
    )
    assert likelihoods[h_far_id] == pytest.approx(
        stats.norm.logpdf(3.0, loc=0.0, scale=convolved_sigma),
        rel=1e-5,
    )


def test_compare_errors_when_all_hypotheses_have_zero_support():
    pkg = CollectedPackage(name="bayes_zero_support_pkg", namespace="t")
    token = _current_package.set(pkg)
    try:
        theta = Variable(symbol="theta", domain=Probability)
        k = Variable(symbol="k", domain=Nat, value=3)
        h_low = parameter(theta, 0.2, content="theta = 0.2.", prior=0.5, label="h_low")
        h_high = parameter(theta, 0.8, content="theta = 0.8.", prior=0.5, label="h_high")
        data = observe(k, value=3, label="data", rationale="Observed impossible k = 3.")
        model_low = bayes.predict(
            h_low,
            target=k,
            distribution=Binomial("k under low", n=1, p=theta),
            label="model_low",
        )
        model_high = bayes.predict(
            h_high,
            target=k,
            distribution=Binomial("k under high", n=1, p=theta),
            label="model_high",
        )
        bayes.compare(data, models=[model_low, model_high], label="cmp")
    finally:
        _current_package.reset(token)

    with pytest.raises(ValueError, match="zero support"):
        compile_package_artifact(pkg)


def test_compare_does_not_duplicate_existing_pairwise_contradiction():
    pkg = CollectedPackage(name="bayes_mendel_pkg", namespace="t")
    token = _current_package.set(pkg)
    try:
        theta = Variable(symbol="theta", domain=Probability)
        k = Variable(symbol="k", domain=Nat, value=295)
        h_31 = parameter(theta, 0.75, content="theta = 0.75.", prior=0.5, label="h_3_1")
        h_null = parameter(theta, 0.5, content="theta = 0.5.", prior=0.5, label="h_null")
        data = observe(k, value=295, label="data", rationale="Observed k = 295.")
        model_31 = bayes.predict(
            h_31,
            target=k,
            distribution=Binomial("k under 3:1", n=395, p=theta),
            label="model_31",
        )
        model_null = bayes.predict(
            h_null,
            target=k,
            distribution=Binomial("k under null", n=395, p=theta),
            label="model_null",
        )
        contradict(h_31, h_null, label="manual_contradiction")
        bayes.compare(
            data,
            models=[model_31, model_null],
            exclusivity="pairwise_contradiction",
            label="cmp",
        )
    finally:
        _current_package.reset(token)

    compiled = compile_package_artifact(pkg)
    h_31_id = compiled.knowledge_ids_by_object[id(h_31)]
    h_null_id = compiled.knowledge_ids_by_object[id(h_null)]
    contradiction_ops = [
        op
        for op in compiled.graph.operators
        if op.operator == "contradiction" and set(op.variables) == {h_31_id, h_null_id}
    ]

    assert len(contradiction_ops) == 1
    assert contradiction_ops[0].metadata["action_label"].endswith("::action::manual_contradiction")


def test_multiple_compares_reuse_auto_generated_pairwise_contradiction():
    pkg, h_31, h_null, _data, model_31, model_null, _cmp_result = _compiled_mendel_bayes(
        exclusivity="pairwise_contradiction"
    )
    token = _current_package.set(pkg)
    try:
        k2 = Variable(symbol="k", domain=Nat, value=300)
        data2 = observe(k2, value=300, label="data2", rationale="Observed replicate k = 300.")
        bayes.compare(
            data2,
            models=[model_31, model_null],
            exclusivity="pairwise_contradiction",
            label="cmp2",
        )
    finally:
        _current_package.reset(token)

    compiled = compile_package_artifact(pkg)
    h_31_id = compiled.knowledge_ids_by_object[id(h_31)]
    h_null_id = compiled.knowledge_ids_by_object[id(h_null)]
    contradiction_ops = [
        op
        for op in compiled.graph.operators
        if op.operator == "contradiction" and set(op.variables) == {h_31_id, h_null_id}
    ]

    assert len(contradiction_ops) == 1
    assert (
        contradiction_ops[0]
        .metadata["action_label"]
        .endswith("::action::f2_likelihood_contradict_h_3_1_h_null")
    )


def test_exhaustive_equal_prior_argmax_tracks_largest_log_likelihood():
    pkg = CollectedPackage(name="bayes_argmax_pkg", namespace="t")
    token = _current_package.set(pkg)
    try:
        theta = Variable(symbol="theta", domain=Probability)
        k = Variable(symbol="k", domain=Nat, value=4)
        h_low = parameter(theta, 0.2, content="theta = 0.2.", prior=1 / 3, label="h_low")
        h_mid = parameter(theta, 0.5, content="theta = 0.5.", prior=1 / 3, label="h_mid")
        h_high = parameter(theta, 0.8, content="theta = 0.8.", prior=1 / 3, label="h_high")
        data = observe(k, value=4, label="data", rationale="Observed k = 4.")
        model_low = bayes.predict(
            h_low, target=k, distribution=Binomial("k under low", n=5, p=theta), label="model_low"
        )
        model_mid = bayes.predict(
            h_mid, target=k, distribution=Binomial("k under mid", n=5, p=theta), label="model_mid"
        )
        model_high = bayes.predict(
            h_high,
            target=k,
            distribution=Binomial("k under high", n=5, p=theta),
            label="model_high",
        )
        comparison = bayes.compare(
            data,
            models=[model_low, model_mid, model_high],
            exclusivity="exhaustive_pairwise_complement",
            precomputed={h_low: -4.0, h_mid: -2.0, h_high: -1.0},
            label="cmp",
        )
    finally:
        _current_package.reset(token)

    compiled = compile_package_artifact(pkg)
    beliefs, _ = exact_inference(lower_local_graph(compiled.graph))
    hypothesis_ids = {
        h_low: compiled.knowledge_ids_by_object[id(h_low)],
        h_mid: compiled.knowledge_ids_by_object[id(h_mid)],
        h_high: compiled.knowledge_ids_by_object[id(h_high)],
    }
    posterior_winner = max(hypothesis_ids, key=lambda h: beliefs[hypothesis_ids[h]])

    assert posterior_winner is h_high
    assert beliefs[compiled.knowledge_ids_by_object[id(comparison)]] > 0.99


def test_full_pipeline_mendel_with_real_binomial_no_precomputed():
    pkg, h_31, h_null, _data, _model_31, _model_null, cmp_result = _compiled_mendel_bayes(
        exclusivity="exhaustive_pairwise_complement"
    )

    compiled = compile_package_artifact(pkg)
    h_31_id = compiled.knowledge_ids_by_object[id(h_31)]
    h_null_id = compiled.knowledge_ids_by_object[id(h_null)]
    cmp_id = compiled.knowledge_ids_by_object[id(cmp_result)]

    cmp_ir = next(k for k in compiled.graph.knowledges if k.id == cmp_id)
    likelihoods = cmp_ir.metadata["comparison"]["likelihoods"]
    assert likelihoods[h_31_id] == pytest.approx(stats.binom(n=395, p=0.75).logpmf(295), rel=1e-6)
    assert likelihoods[h_null_id] == pytest.approx(stats.binom(n=395, p=0.5).logpmf(295), rel=1e-6)

    beliefs, _ = exact_inference(lower_local_graph(compiled.graph))
    odds = beliefs[h_31_id] / beliefs[h_null_id]
    assert odds > 100.0
    assert beliefs[h_31_id] > 0.95
    assert beliefs[h_null_id] < 0.03
    assert beliefs[cmp_id] > 0.99
