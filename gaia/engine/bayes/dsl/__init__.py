"""Bayes DSL verbs."""

from gaia.engine.bayes.dsl.model import model


def compare(*args, **kwargs):
    """Compare predictive models against data."""
    from gaia.engine.bayes.dsl.compare import compare as _compare

    return _compare(*args, **kwargs)


__all__ = ["compare", "model"]
