"""Context packet builder for gaia inquiry context."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from gaia.cli.commands._inquiry import InquiryEdge, InquiryNode, build_goal_trees
from gaia.engine.inquiry.focus import FocusBinding, resolve_focus_target
from gaia.engine.inquiry.review_manifest import load_or_generate_review_manifest
from gaia.engine.inquiry.state import InquiryState, load_state
from gaia.engine.packaging import (
    apply_package_priors,
    compile_loaded_package_artifact,
    ensure_package_env,
    load_gaia_package,
)

TrajectorySelector = Literal["most_uncertain", "shortest"]
RenderOrder = Literal["backward", "forward"]


@dataclass(frozen=True)
class ContextRouteStep:
    edge_kind: str
    target_id: str | None
    label: str
    status: str | None
    conclusion_id: str
    premise_ids: list[str]
    background_ids: list[str]
    rationale: str | None


@dataclass(frozen=True)
class ContextPacket:
    focus: FocusBinding
    trajectory: TrajectorySelector
    order: RenderOrder
    route: list[ContextRouteStep]
    ir: dict[str, Any]
    source_ir: dict[str, Any]
    state: InquiryState


def build_context_packet(
    path: str | Path,
    *,
    focus_override: str | None,
    trajectory: TrajectorySelector,
    order: RenderOrder,
) -> ContextPacket:
    pkg_path = Path(path).resolve()
    state = load_state(pkg_path)
    focus_raw = focus_override if focus_override is not None else state.focus
    if focus_raw is None:
        raise ValueError("No inquiry focus set; pass --focus or run gaia inquiry focus <claim>.")

    ensure_package_env(pkg_path)
    loaded = load_gaia_package(str(pkg_path))
    apply_package_priors(loaded)
    compiled = compile_loaded_package_artifact(loaded)
    graph = compiled.graph
    review_manifest = load_or_generate_review_manifest(loaded.pkg_path, compiled)

    focus = resolve_focus_target(focus_raw, graph)
    if focus.resolved_id is None or focus.kind != "claim":
        raise ValueError(f"Focus {focus_raw!r} did not resolve to a claim.")

    source_ir = compiled.to_json()
    trees = build_goal_trees(
        source_ir,
        review_manifest,
        exported_ids={focus.resolved_id},
        formalization_manifest=compiled.formalization_manifest,
    )
    if not trees:
        route: list[ContextRouteStep] = []
    else:
        routes = _enumerate_routes(trees[0])
        route = _select_route(routes, trajectory, state, source_ir)

    return ContextPacket(
        focus=focus,
        trajectory=trajectory,
        order=order,
        route=route,
        ir=_build_ir_slice(source_ir, route, focus.resolved_id),
        source_ir=source_ir,
        state=state,
    )


def _route_step(edge: InquiryEdge, conclusion_id: str) -> ContextRouteStep:
    return ContextRouteStep(
        edge_kind=edge.kind,
        target_id=edge.target_id,
        label=edge.label,
        status=edge.status,
        conclusion_id=edge.conclusion_id or conclusion_id,
        premise_ids=list(edge.premise_ids),
        background_ids=list(edge.background_ids),
        rationale=edge.rationale,
    )


def _enumerate_routes(node: InquiryNode) -> list[list[ContextRouteStep]]:
    if not node.incoming:
        return [[]]
    routes: list[list[ContextRouteStep]] = []
    for edge in node.incoming:
        step = _route_step(edge, node.knowledge_id)
        if not edge.inputs:
            routes.append([step])
            continue
        for child in edge.inputs:
            for child_route in _enumerate_routes(child):
                routes.append([step, *child_route])
    return routes


def _select_route(
    routes: list[list[ContextRouteStep]],
    trajectory: TrajectorySelector,
    state: InquiryState,
    ir: dict[str, Any],
) -> list[ContextRouteStep]:
    if not routes:
        return []
    if trajectory == "shortest":
        return min(routes, key=lambda route: (len(route), _route_key(route)))
    return sorted(
        routes,
        key=lambda route: (-_uncertainty_score(route, state, ir), len(route), _route_key(route)),
    )[0]


def _route_key(route: list[ContextRouteStep]) -> tuple[str, ...]:
    return tuple(step.target_id or step.label for step in route)


def _known_knowledge_ids(ir: dict[str, Any]) -> set[str]:
    return {item["id"] for item in ir.get("knowledges", []) if item.get("id")}


def _uncertainty_score(
    route: list[ContextRouteStep],
    state: InquiryState,
    ir: dict[str, Any],
) -> int:
    known = _known_knowledge_ids(ir)
    obligation_targets = {item.target_qid for item in state.synthetic_obligations}
    rejected_targets = {item.target_strategy for item in state.synthetic_rejections}
    score = 0
    for step in route:
        if step.target_id in rejected_targets:
            score += 6
        if step.target_id in obligation_targets or step.conclusion_id in obligation_targets:
            score += 4
        if step.status == "rejected":
            score += 6
        elif step.status == "needs_inputs":
            score += 5
        elif step.status == "unreviewed":
            score += 2
        if not step.rationale:
            score += 2
        for ref in [*step.premise_ids, *step.background_ids, step.conclusion_id]:
            if ref and ref not in known:
                score += 5
    if route:
        last_premises = route[-1].premise_ids
        if last_premises and any(ref in known for ref in last_premises):
            score += 1
    return score


def _build_ir_slice(
    ir: dict[str, Any],
    route: list[ContextRouteStep],
    focus_id: str,
) -> dict[str, Any]:
    knowledge_ids = {focus_id}
    strategy_ids: set[str] = set()
    for step in route:
        knowledge_ids.add(step.conclusion_id)
        knowledge_ids.update(step.premise_ids)
        knowledge_ids.update(step.background_ids)
        if step.edge_kind == "strategy" and step.target_id:
            strategy_ids.add(step.target_id)

    knowledges = [item for item in ir.get("knowledges", []) if item.get("id") in knowledge_ids]
    strategies = [
        item for item in ir.get("strategies", []) if item.get("strategy_id") in strategy_ids
    ]

    return {
        "namespace": ir.get("namespace"),
        "package_name": ir.get("package_name"),
        "scope": ir.get("scope", "local"),
        "knowledges": knowledges,
        "strategies": strategies,
        "operators": [],
        "composes": [],
        "formula_graphs": [],
    }
