"""``gaia build check`` diagnostics for Bayes predict / compare packages."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from gaia.cli.main import app

runner = CliRunner()


def _write_package(pkg_dir: Path, source: str) -> None:
    pkg_dir.mkdir()
    (pkg_dir / "pyproject.toml").write_text(
        '[project]\nname = "bayes-check-gaia"\nversion = "0.1.0"\n\n'
        '[tool.gaia]\nnamespace = "github"\ntype = "knowledge-package"\n'
    )
    src = pkg_dir / "bayes_check"
    src.mkdir()
    (src / "__init__.py").write_text(source)


def test_check_reports_dangling_prediction_and_unobserved_target(tmp_path: Path):
    """A predict() not consumed by compare() AND not observed surfaces two warnings."""
    pkg_dir = tmp_path / "bayes_check"
    _write_package(
        pkg_dir,
        """
import gaia.engine.bayes as bayes
from gaia.engine.lang import Binomial, Nat, Probability, Variable, parameter

theta = Variable(symbol="theta", domain=Probability)
k = Variable(symbol="k", domain=Nat)
h = parameter(theta, 0.5, label="h", prior=0.5)
model = bayes.predict(
    h,
    target=k,
    distribution=Binomial("k under h", n=10, p=theta),
    label="model",
)

__all__ = ["h", "model"]
""",
    )

    result = runner.invoke(app, ["build", "check", str(pkg_dir)])

    assert result.exit_code == 0, result.output
    assert "bayes:dangling-prediction" in result.output
    assert "model" in result.output
    assert "bayes:unobserved-prediction-target" in result.output
    assert "'k'" in result.output
    assert "observe(target, value=...)" in result.output


def test_check_errors_when_pairwise_hypothesis_priors_exceed_one(tmp_path: Path):
    pkg_dir = tmp_path / "bayes_check"
    _write_package(
        pkg_dir,
        """
import gaia.engine.bayes as bayes
from gaia.engine.lang import (
    Binomial, Nat, Probability, Variable, observe, parameter,
)

theta = Variable(symbol="theta", domain=Probability)
k = Variable(symbol="k", domain=Nat, value=3)
h1 = parameter(theta, 0.3, label="h1", prior=0.7)
h2 = parameter(theta, 0.7, label="h2", prior=0.6)
data = observe(k, value=3, label="data", rationale="Observed k = 3.")
model1 = bayes.predict(
    h1, target=k, distribution=Binomial("k under h1", n=5, p=theta), label="model1"
)
model2 = bayes.predict(
    h2, target=k, distribution=Binomial("k under h2", n=5, p=theta), label="model2"
)
# Explicit ``pairwise_contradiction`` so this test exercises the
# at-most-one prior-coherence rule (the default is exhaustive).
cmp = bayes.compare(
    data,
    models=[model1, model2],
    exclusivity="pairwise_contradiction",
    label="cmp",
)

__all__ = ["h1", "h2", "data", "model1", "model2", "cmp"]
""",
    )

    result = runner.invoke(app, ["build", "check", str(pkg_dir)])

    assert result.exit_code != 0
    assert "bayes:hypothesis-prior-coherence" in result.output
    assert "pairwise_contradiction" in result.output
    assert "sum=1.3" in result.output


def test_check_errors_when_exhaustive_hypothesis_priors_do_not_sum_to_one(tmp_path: Path):
    pkg_dir = tmp_path / "bayes_check"
    _write_package(
        pkg_dir,
        """
import gaia.engine.bayes as bayes
from gaia.engine.lang import (
    Binomial, Nat, Probability, Variable, observe, parameter,
)

theta = Variable(symbol="theta", domain=Probability)
k = Variable(symbol="k", domain=Nat, value=3)
h1 = parameter(theta, 0.3, label="h1", prior=0.6)
h2 = parameter(theta, 0.7, label="h2", prior=0.2)
data = observe(k, value=3, label="data", rationale="Observed k = 3.")
model1 = bayes.predict(
    h1, target=k, distribution=Binomial("k under h1", n=5, p=theta), label="model1"
)
model2 = bayes.predict(
    h2, target=k, distribution=Binomial("k under h2", n=5, p=theta), label="model2"
)
cmp = bayes.compare(
    data,
    models=[model1, model2],
    exclusivity="exhaustive_pairwise_complement",
    label="cmp",
)

__all__ = ["h1", "h2", "data", "model1", "model2", "cmp"]
""",
    )

    result = runner.invoke(app, ["build", "check", str(pkg_dir)])

    assert result.exit_code != 0
    assert "bayes:hypothesis-prior-coherence" in result.output
    assert "exhaustive_pairwise_complement" in result.output
    assert "sum=0.8" in result.output


def test_check_errors_when_compare_data_has_no_observation_binding(tmp_path: Path):
    """A compare() ``data`` Claim with no observation metadata fires comparison-without-data."""
    pkg_dir = tmp_path / "bayes_check"
    _write_package(
        pkg_dir,
        """
import gaia.engine.bayes as bayes
from gaia.engine.lang import (
    Binomial, Nat, Probability, Variable, claim, parameter,
)

theta = Variable(symbol="theta", domain=Probability)
k = Variable(symbol="k", domain=Nat)
h1 = parameter(theta, 0.3, label="h1", prior=0.5)
h2 = parameter(theta, 0.7, label="h2", prior=0.5)
# Plain claim — no metadata["observation"] payload, so compare() can't
# locate the observed value through the unified schema.
data = claim("A data claim without an observation payload.", label="data")
model1 = bayes.predict(
    h1, target=k, distribution=Binomial("k under h1", n=5, p=theta), label="model1"
)
model2 = bayes.predict(
    h2, target=k, distribution=Binomial("k under h2", n=5, p=theta), label="model2"
)
cmp = bayes.compare(
    data,
    models=[model1, model2],
    precomputed={h1: -1.0, h2: -2.0},
    label="cmp",
)

__all__ = ["h1", "h2", "data", "model1", "model2", "cmp"]
""",
    )

    result = runner.invoke(app, ["build", "check", str(pkg_dir)])

    assert result.exit_code != 0
    assert "bayes:comparison-without-data" in result.output
    assert "data" in result.output
    assert "observe(target, value=...)" in result.output
