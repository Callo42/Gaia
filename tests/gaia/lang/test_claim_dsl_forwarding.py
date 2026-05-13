"""Tests for claim() DSL surface and its interaction with register_prior().

In v0.5+ the prior pipeline is multi-source. Two author-facing entry points:

- ``claim(content, prior=X)`` — convenience shortcut equivalent to
  ``register_prior(c, X, source_id="claim_inline", justification="(inline ...)")``.
  Inline priors sit at the lowest deliberate tier of the default
  ResolutionPolicy priority order.
- ``register_prior(c, value=..., justification=..., source_id=...)`` — the
  canonical, ranked-above-inline path. Use this whenever the prior is
  load-bearing and deserves a documented justification.

Any explicit ``register_prior()`` call wins over the inline shortcut.
"""

import pytest

from gaia.lang import (
    ClaimKind,
    Constant,
    Equals,
    Probability,
    Variable,
    claim,
    register_prior,
)
from gaia.lang.dsl.register_prior import (
    DEFAULT_SOURCE_ID,
    PRIOR_RECORDS_METADATA_KEY,
)


def test_dsl_claim_forwards_inline_prior_as_claim_inline_record():
    """claim(prior=X) routes through register_prior(source_id='claim_inline')."""
    c = claim("test", prior=0.5)
    records = c.metadata[PRIOR_RECORDS_METADATA_KEY]
    assert len(records) == 1
    assert records[0]["value"] == 0.5
    assert records[0]["source_id"] == "claim_inline"
    assert "inline default" in records[0]["justification"]
    # The Claim.prior attribute is intentionally NOT set — inline priors flow
    # only through the prior_records pipeline so resolution can override them.
    assert c.prior is None


def test_dsl_claim_forwards_formula():
    """formula= still forwards through DSL claim()."""
    p = Variable(symbol="p", domain=Probability)
    eq = Equals(p, Constant(0.75, Probability))

    c = claim("p = 0.75", formula=eq)

    assert c.formula is eq
    assert "formula" not in c.metadata


def test_dsl_claim_forwards_kind():
    """kind= still forwards through DSL claim()."""
    p = Variable(symbol="p", domain=Probability)
    eq = Equals(p, Constant(0.75, Probability))

    c = claim("p = 0.75", formula=eq, kind=ClaimKind.PARAMETER)

    assert c.kind is ClaimKind.PARAMETER
    assert "kind" not in c.metadata


def test_dsl_claim_default_kind_general():
    """Bare claim() defaults to GENERAL kind, no formula, no prior."""
    c = claim("plain")
    assert c.kind is ClaimKind.GENERAL
    assert c.formula is None
    assert c.prior is None
    # No prior_records yet because no prior was set.
    assert PRIOR_RECORDS_METADATA_KEY not in c.metadata


def test_dsl_claim_other_metadata_still_passes_through():
    """Genuine metadata keys (custom annotations) still flow into c.metadata."""
    c = claim("test", custom_tag="foo", another="bar")
    assert c.metadata.get("custom_tag") == "foo"
    assert c.metadata.get("another") == "bar"


def test_register_prior_overrides_claim_inline_under_default_policy():
    """Explicit register_prior() with default source_id beats the inline shortcut."""
    from gaia.ir import default_resolution_policy
    from gaia.lang.dsl.register_prior import resolve_priors_to_metadata

    c = claim("Subject p smokes daily.", prior=0.3)
    register_prior(c, 0.45, justification="adjusted after literature review")

    records = c.metadata[PRIOR_RECORDS_METADATA_KEY]
    assert len(records) == 2
    assert {r["source_id"] for r in records} == {"claim_inline", "user_priors"}

    resolve_priors_to_metadata([c], default_resolution_policy())
    assert c.metadata["prior"] == 0.45
    assert "literature review" in c.metadata["prior_justification"]
    assert c.metadata["prior_source_id"] == "user_priors"


def test_register_prior_appends_record_with_default_source():
    """register_prior() with default source_id stores a 'user_priors' record."""
    c = claim("Subject S smokes daily.")
    register_prior(c, value=0.3, justification="literature base rate")
    records = c.metadata[PRIOR_RECORDS_METADATA_KEY]
    assert len(records) == 1
    assert records[0]["value"] == 0.3
    assert records[0]["source_id"] == DEFAULT_SOURCE_ID
    assert records[0]["justification"] == "literature base rate"
    assert "created_at" in records[0]


def test_register_prior_supports_multiple_named_sources():
    """Calling register_prior twice with different sources yields two records."""
    c = claim("Subject S smokes daily.")
    register_prior(c, value=0.3, justification="literature")
    register_prior(
        c,
        value=0.45,
        source_id="continuous_inference",
        justification="posterior mean from continuous engine",
    )
    records = c.metadata[PRIOR_RECORDS_METADATA_KEY]
    assert len(records) == 2
    assert {r["source_id"] for r in records} == {"user_priors", "continuous_inference"}


def test_register_prior_rejects_non_claim():
    with pytest.raises(TypeError, match="must be a Claim"):
        register_prior("not a claim", 0.5, justification="bad")  # type: ignore[arg-type]


def test_register_prior_rejects_out_of_bounds():
    c = claim("Bound test.")
    with pytest.raises(ValueError, match="Cromwell bounds"):
        register_prior(c, 1.0, justification="boundary")
    with pytest.raises(ValueError, match="Cromwell bounds"):
        register_prior(c, 0.0, justification="boundary")
    with pytest.raises(ValueError, match="Cromwell bounds"):
        register_prior(c, -0.1, justification="negative")


def test_register_prior_rejects_empty_justification():
    c = claim("Justification test.")
    with pytest.raises(ValueError, match="non-empty justification"):
        register_prior(c, 0.5, justification="")
    with pytest.raises(ValueError, match="non-empty justification"):
        register_prior(c, 0.5, justification="   ")


def test_register_prior_rejects_empty_source_id():
    c = claim("Source test.")
    with pytest.raises(ValueError, match="non-empty string"):
        register_prior(c, 0.5, source_id="", justification="reason")


def test_register_prior_rejects_bool_value():
    """Booleans must not silently coerce to 0/1."""
    c = claim("Bool test.")
    with pytest.raises(TypeError, match="numeric scalar"):
        register_prior(c, True, justification="bad")  # type: ignore[arg-type]
