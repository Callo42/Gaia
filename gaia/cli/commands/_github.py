"""Orchestrate GitHub output generation for a compiled Gaia package.

Combines wiki pages, graph.json, manifest.json, assets, section placeholders,
a React SPA template, and a README skeleton into a single ``.github-output/`` directory.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from gaia.cli.commands._graph_json import write_graph_json
from gaia.cli.commands._manifest import generate_manifest
from gaia.cli.commands._wiki import (
    generate_wiki_home,
    generate_wiki_inference,
    generate_wiki_module,
)
from gaia.ir.coarsen import coarsen_ir


_MAX_MI_PREMISES = 12
_MAX_MI_GRAPH_ITEMS = 2500


def _strategy_params_from_param_data(param_data: dict | None) -> dict[str, list[float]]:
    strat_params: dict[str, list[float]] = {}
    if not param_data:
        return strat_params
    for sp in param_data.get("strategy_params", []):
        sid = sp.get("strategy_id", "")
        if sp.get("conditional_probabilities"):
            strat_params[sid] = sp["conditional_probabilities"]
        elif sp.get("conditional_probability") is not None:
            strat_params[sid] = [sp["conditional_probability"]]
    return strat_params


def _safe_mi_strategy_indices(ir: dict, coarse: dict) -> set[int]:
    graph_items = (
        len(ir.get("knowledges", [])) + len(ir.get("strategies", [])) + len(ir.get("operators", []))
    )
    if graph_items > _MAX_MI_GRAPH_ITEMS:
        return set()
    return {
        i
        for i, strategy in enumerate(coarse.get("strategies", []))
        if len(strategy.get("premises", [])) <= _MAX_MI_PREMISES
    }


def _compute_mi_map(
    ir: dict,
    coarse: dict,
    *,
    node_priors: dict[str, float],
    param_data: dict | None = None,
) -> dict[int, float]:
    """Compute optional MI annotations only for bounded-size coarse strategies."""
    indices = _safe_mi_strategy_indices(ir, coarse)
    if not indices:
        return {}

    try:
        from gaia.ir.coarsen import compute_coarse_cpts, mutual_information

        cpts = compute_coarse_cpts(
            ir,
            coarse,
            node_priors=node_priors,
            strategy_params=_strategy_params_from_param_data(param_data),
            strategy_indices=indices,
        )
        mi_map: dict[int, float] = {}
        for i, cpt in cpts.items():
            if len(cpt) < 2:
                continue
            premise_priors = [node_priors.get(p, 0.5) for p in coarse["strategies"][i]["premises"]]
            mi_map[i] = mutual_information(cpt, premise_priors)
        return mi_map
    except Exception:
        return {}


def _node_priors_for_optional_mi(
    ir: dict,
    explicit_priors: dict[str, float] | None = None,
) -> dict[str, float]:
    _CROMWELL_EPS = 1e-3
    node_priors: dict[str, float] = {}
    for k in ir.get("knowledges", []):
        kid = k["id"]
        meta = k.get("metadata") or {}
        helper_kind = meta.get("helper_kind", "")
        if helper_kind in (
            "implication_result",
            "equivalence_result",
            "contradiction_result",
            "complement_result",
        ):
            node_priors[kid] = 1.0 - _CROMWELL_EPS
        else:
            node_priors[kid] = 0.5
    if explicit_priors:
        node_priors.update(explicit_priors)
    return node_priors


def _copy_react_template(docs_dir: Path) -> None:
    """Copy the React SPA template from ``gaia.cli.templates.pages`` to *docs_dir*.

    The template provides the scaffold (``package.json``, ``src/``, ``index.html``,
    etc.) on top of which data files (``public/data/``, ``public/assets/``) are
    overlaid by the caller.

    ``node_modules``, ``dist``, ``package-lock.json``, and Python bytecode are
    excluded from the copy so the output stays lightweight and reproducible.
    """
    import gaia.cli.templates.pages as pages_pkg

    template_path = Path(pages_pkg.__file__).parent

    if docs_dir.exists():
        shutil.rmtree(docs_dir)

    shutil.copytree(
        template_path,
        docs_dir,
        ignore=shutil.ignore_patterns(
            "node_modules", "dist", "package-lock.json", "__pycache__", "*.pyc"
        ),
    )


def _write_meta_json(
    data_dir: Path,
    ir: dict,
    pkg_metadata: dict,
) -> None:
    """Write ``meta.json`` with package identity and description."""
    meta = {
        "package_name": ir.get("package_name", ""),
        "namespace": ir.get("namespace", ""),
        "name": pkg_metadata.get("name", ir.get("package_name", "")),
        "description": pkg_metadata.get("description", ""),
    }
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def generate_github_output(
    ir: dict,
    pkg_path: Path,
    *,
    beliefs_data: dict | None = None,
    param_data: dict | None = None,
    exported_ids: set[str] | None = None,
    pkg_metadata: dict | None = None,
) -> Path:
    """Generate the full ``.github-output/`` tree and return its path.

    Steps:
    0. Copy React SPA template to ``docs/``
    1. Create remaining directory structure
    2. Write wiki pages
    3. Write ``docs/public/data/graph.json``
    4. Copy ``beliefs.json`` if beliefs_data is available
    5. Write ``docs/public/data/meta.json``
    6. Copy artifacts to ``docs/public/assets/``
    7. Create section placeholder files (one per module)
    8. Write ``manifest.json``
    9. Generate README.md skeleton
    10. Return the output directory path
    """
    exported = exported_ids or set()
    metadata = pkg_metadata or {}

    output_dir = pkg_path / ".github-output"
    docs_dir = output_dir / "docs"
    wiki_dir = output_dir / "wiki"
    data_dir = docs_dir / "public" / "data"
    assets_dir = docs_dir / "public" / "assets"
    sections_dir = data_dir / "sections"

    # ── 0. Copy React template (provides package.json, src/, index.html, …) ──
    _copy_react_template(docs_dir)

    # Create remaining directory structure (template may already provide some)
    for d in (wiki_dir, data_dir, assets_dir, sections_dir):
        d.mkdir(parents=True, exist_ok=True)

    # ── 1. Wiki pages + section content ──
    wiki_page_names: list[str] = []

    home_content = generate_wiki_home(ir, beliefs_data=beliefs_data)
    (wiki_dir / "Home.md").write_text(home_content, encoding="utf-8")
    wiki_page_names.append("Home.md")

    modules: set[str] = set()
    for k in ir.get("knowledges", []):
        modules.add(k.get("module") or "Root")

    for mod in sorted(modules):
        filename = f"Module-{mod.replace('_', '-')}.md"
        content = generate_wiki_module(
            ir,
            mod,
            beliefs_data=beliefs_data,
            param_data=param_data,
        )
        (wiki_dir / filename).write_text(content, encoding="utf-8")
        wiki_page_names.append(filename)
        (sections_dir / f"{mod}.md").write_text(content, encoding="utf-8")

    if beliefs_data is not None:
        inference_content = generate_wiki_inference(
            ir,
            beliefs_data,
            param_data=param_data,
        )
        (wiki_dir / "Inference-Results.md").write_text(inference_content, encoding="utf-8")
        wiki_page_names.append("Inference-Results.md")

    # ── 2. graph.json ──
    write_graph_json(
        data_dir / "graph.json",
        ir,
        beliefs_data=beliefs_data,
        param_data=param_data,
        exported_ids=exported,
    )

    # ── 3. beliefs.json (if available) ──
    if beliefs_data is not None:
        with (data_dir / "beliefs.json").open("w", encoding="utf-8") as f:
            json.dump(beliefs_data, f, indent=2, ensure_ascii=False)

    # ── 4. meta.json ──
    _write_meta_json(data_dir, ir, metadata)

    # ── 5. Copy artifacts to assets (recursive) ──
    artifacts_dir = pkg_path / "artifacts"
    asset_names: list[str] = []
    if artifacts_dir.is_dir():
        for item in sorted(artifacts_dir.rglob("*")):
            if item.is_file():
                rel = item.relative_to(artifacts_dir)
                dest = assets_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)
                asset_names.append(str(rel))

    # ── 7. manifest.json ──
    manifest_json = generate_manifest(
        ir,
        exported,
        wiki_page_names,
        assets=asset_names,
    )
    (output_dir / "manifest.json").write_text(manifest_json, encoding="utf-8")

    # ── 8. Narrative outline (for agent consumption) ──
    # Split into two phases: outline (always fast) and MI (may be slow)
    try:
        from gaia.ir.linearize import linearize_narrative, render_narrative_outline

        coarse_for_outline = coarsen_ir(ir, exported)
        explicit_priors = (
            {p["knowledge_id"]: p["value"] for p in param_data.get("priors", [])}
            if param_data
            else {}
        )
        node_priors = _node_priors_for_optional_mi(ir, explicit_priors)
        mi_map = _compute_mi_map(
            ir,
            coarse_for_outline,
            node_priors=node_priors,
            param_data=param_data,
        )

        # Phase 2: generate outline (always works, with or without MI)
        b = (
            {x["knowledge_id"]: x["belief"] for x in beliefs_data.get("beliefs", [])}
            if beliefs_data
            else {}
        )
        sections = linearize_narrative(
            coarse_for_outline, beliefs=b, priors=node_priors, mi_per_strategy=mi_map
        )
        outline = render_narrative_outline(sections)
        (output_dir / "narrative-outline.md").write_text(outline, encoding="utf-8")
    except Exception:
        pass  # Outline generation failed entirely

    # ── 9. README.md skeleton ──
    readme = _generate_readme_skeleton(
        ir,
        beliefs_data=beliefs_data,
        param_data=param_data,
        exported_ids=exported,
        pkg_metadata=metadata,
    )
    (output_dir / "README.md").write_text(readme, encoding="utf-8")

    return output_dir


def _render_coarse_mermaid(
    ir: dict,
    beliefs: dict[str, float],
    priors: dict[str, float],
    exported_ids: set[str],
    param_data: dict | None = None,
) -> str:
    """Render a coarse-grained Mermaid graph: leaf premises → exported conclusions."""
    coarse = coarsen_ir(ir, exported_ids)
    kid_to_k = {k["id"]: k for k in coarse["knowledges"]}

    lines = [
        "```mermaid",
        "---",
        "config:",
        "  flowchart:",
        "    rankSpacing: 80",
        "    nodeSpacing: 30",
        "---",
        "graph TB",
    ]

    for k in coarse["knowledges"]:
        kid = k["id"]
        label = k.get("title") or k.get("label", "?")
        safe = k.get("label", "x").replace("-", "_")
        b = beliefs.get(kid)
        p = priors.get(kid)
        is_exp = kid in exported_ids

        prior_val = p if p is not None else 0.5
        if is_exp:
            ann = f"{prior_val:.2f} → {b:.2f}" if b is not None else ""
            display = f"★ {label}\\n({ann})" if ann else f"★ {label}"
            css = ":::exported"
        else:
            ann = f"{prior_val:.2f} → {b:.2f}" if b is not None else f"{prior_val:.2f}"
            display = f"{label}\\n({ann})"
            css = ":::premise"

        display = display.replace('"', "#quot;").replace("*", "#ast;")
        lines.append(f'    {safe}["{display}"]{css}')

    # Strategy intermediate nodes (stadium shape) with CPT annotation
    _DETERMINISTIC = {
        "deduction",
        "reductio",
        "elimination",
        "mathematical_induction",
        "case_analysis",
    }

    mi_map: dict[int, float] = {}
    if beliefs:
        node_priors_for_mi = _node_priors_for_optional_mi(ir, priors)
        mi_map = _compute_mi_map(
            ir,
            coarse,
            node_priors=node_priors_for_mi,
            param_data=param_data,
        )

    total_mi = 0.0
    for i, s in enumerate(coarse["strategies"]):
        stype = s.get("type", "infer")
        sid = f"strat_{i}"
        conc = kid_to_k.get(s["conclusion"], {}).get("label", "?").replace("-", "_")
        css = "" if stype in _DETERMINISTIC else ":::weak"

        mi = mi_map.get(i)
        if mi is not None:
            total_mi += mi
            ann = f"{stype}\\n{mi:.2f} bits"
        else:
            ann = stype

        lines.append(f'    {sid}(["{ann}"]){css}')
        for p in s["premises"]:
            prem = kid_to_k.get(p, {}).get("label", "?").replace("-", "_")
            lines.append(f"    {prem} --> {sid}")
        lines.append(f"    {sid} --> {conc}")

    # Operator nodes (hexagon shape)
    _OP_SYMBOLS = {
        "contradiction": "\u2297",
        "equivalence": "\u2261",
        "complement": "\u2295",
        "disjunction": "\u2228",
        "implication": "\u2192",
    }
    _UNDIRECTED = {"equivalence", "contradiction", "complement", "implication"}
    for i, o in enumerate(coarse.get("operators", [])):
        otype = o.get("operator", "")
        symbol = _OP_SYMBOLS.get(otype, otype)
        oid = f"oper_{i}"
        css = ":::contra" if otype == "contradiction" else ""
        lines.append(f'    {oid}{{{{"{symbol}"}}}}{css}')
        edge = " --- " if otype in _UNDIRECTED else " --> "
        for v in o.get("variables", []):
            v_label = kid_to_k.get(v, {}).get("label", "?").replace("-", "_")
            lines.append(f"    {v_label}{edge}{oid}")
        conc = o.get("conclusion")
        if conc:
            c_label = kid_to_k.get(conc, {}).get("label", "?").replace("-", "_")
            lines.append(f"    {oid}{edge}{c_label}")

    lines.append("")
    lines.append("    classDef premise fill:#ddeeff,stroke:#4488bb,color:#333")
    lines.append("    classDef exported fill:#d4edda,stroke:#28a745,stroke-width:2px,color:#333")
    lines.append("    classDef weak fill:#fff9c4,stroke:#f9a825,stroke-dasharray: 5 5,color:#333")
    lines.append("    classDef contra fill:#ffebee,stroke:#c62828,color:#333")
    lines.append("```")
    return "\n".join(lines), total_mi


def _generate_readme_skeleton(
    ir: dict,
    *,
    beliefs_data: dict | None = None,
    param_data: dict | None = None,
    exported_ids: set[str] | None = None,
    pkg_metadata: dict | None = None,
) -> str:
    """Build a README.md with Mermaid overview, conclusion table, and placeholders."""
    exported = exported_ids or set()
    metadata = pkg_metadata or {}
    pkg_name = metadata.get("name", ir.get("package_name", "Package"))
    description = metadata.get("description", "")

    lines: list[str] = []

    # Title and description
    lines.append(f"# {pkg_name}")
    lines.append("")
    if description:
        lines.append(description)
        lines.append("")

    # Badges placeholder
    lines.append("<!-- badges:start -->")
    lines.append("<!-- badges:end -->")
    lines.append("")

    # Simplified Mermaid graph (only when beliefs are available)
    beliefs: dict[str, float] = {}
    priors: dict[str, float] = {}
    if beliefs_data:
        beliefs = {b["knowledge_id"]: b["belief"] for b in beliefs_data.get("beliefs", [])}
    if param_data:
        priors = {p["knowledge_id"]: p["value"] for p in param_data.get("priors", [])}

    if beliefs:
        lines.append("## Overview")
        lines.append("")
        mermaid, total_mi = _render_coarse_mermaid(
            ir,
            beliefs,
            priors,
            exported,
            param_data=param_data,
        )
        if total_mi > 0:
            lines.append("> [!TIP]")
            lines.append(f"> **Reasoning graph information gain: `{total_mi:.1f} bits`**")
            lines.append(">")
            lines.append(
                "> Total mutual information between leaf premises and "
                "exported conclusions — measures how much the reasoning "
                "structure reduces uncertainty about the results."
            )
            lines.append("")
        lines.append(mermaid)
        lines.append("")

    # Exported conclusions table
    knowledge_by_id = {k["id"]: k for k in ir.get("knowledges", [])}
    exported_nodes = [knowledge_by_id[eid] for eid in sorted(exported) if eid in knowledge_by_id]
    if exported_nodes:
        lines.append("## Conclusions")
        lines.append("")
        lines.append("| Label | Content | Prior | Belief |")
        lines.append("|-------|---------|-------|--------|")
        for k in exported_nodes:
            label = k.get("label", "")
            content = k.get("content", "")
            if len(content) > 80:
                content = content[:77] + "..."
            kid = k["id"]
            prior = f"{priors.get(kid, 0.5):.2f}"
            belief = f"{beliefs[kid]:.2f}" if kid in beliefs else "\u2014"
            lines.append(f"| {label} | {content} | {prior} | {belief} |")
        lines.append("")

    # Placeholder markers
    lines.append("<!-- content:start -->")
    lines.append("<!-- content:end -->")
    lines.append("")

    return "\n".join(lines)
