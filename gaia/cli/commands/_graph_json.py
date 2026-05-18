"""Generate graph.json for interactive visualization (v2).

Strategy and operator entries are promoted to intermediate nodes.
Edges carry a ``role`` field (premise/background/conclusion/variable).
Top-level ``modules`` and ``cross_module_edges`` arrays are computed.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path


def _graph_context(
    ir: dict,
    beliefs_data: dict | None = None,
    param_data: dict | None = None,
    exported_ids: set[str] | None = None,
) -> tuple[dict[str, float], dict[str, float], set[str], dict[str, str], list[dict], list[dict]]:
    beliefs: dict[str, float] = {}
    if beliefs_data:
        beliefs = {b["knowledge_id"]: b["belief"] for b in beliefs_data.get("beliefs", [])}
    priors: dict[str, float] = {}
    if param_data:
        priors = {p["knowledge_id"]: p["value"] for p in param_data.get("priors", [])}
    exported = exported_ids or set()

    kid_module: dict[str, str] = {}
    for k in ir.get("knowledges", []):
        if k.get("module"):
            kid_module[k["id"]] = k["module"]

    module_order: list[str] = list(ir.get("module_order") or [])
    module_node_counts: Counter[str] = Counter()
    strategy_counts: Counter[str] = Counter()
    cross_module: Counter[tuple[str, str]] = Counter()

    for k in ir.get("knowledges", []):
        label = k.get("label", "")
        mod = k.get("module")
        if mod and not label.startswith("__"):
            module_node_counts[mod] += 1

    for s in ir.get("strategies", []):
        conc = s.get("conclusion")
        if not conc:
            continue
        conc_mod = kid_module.get(conc, "")
        strategy_counts[conc_mod] += 1

        for p in s.get("premises", []):
            p_mod = kid_module.get(p, "")
            if p_mod and conc_mod and p_mod != conc_mod:
                cross_module[(p_mod, conc_mod)] += 1

    seen = set(module_order)
    all_mods = list(module_order)
    for mod in sorted(module_node_counts.keys()):
        if mod not in seen:
            all_mods.append(mod)

    modules = [
        {
            "id": mod,
            "order": idx,
            "node_count": module_node_counts.get(mod, 0),
            "strategy_count": strategy_counts.get(mod, 0),
        }
        for idx, mod in enumerate(all_mods)
        if module_node_counts.get(mod, 0) > 0 or strategy_counts.get(mod, 0) > 0
    ]

    cross_module_edges = [
        {"from_module": fm, "to_module": tm, "count": cnt}
        for (fm, tm), cnt in sorted(cross_module.items())
    ]

    return beliefs, priors, exported, kid_module, modules, cross_module_edges


def _iter_nodes(
    ir: dict,
    beliefs: dict[str, float],
    priors: dict[str, float],
    exported: set[str],
    kid_module: dict[str, str],
) -> Iterator[dict]:
    for k in ir["knowledges"]:
        label = k.get("label", "")
        if label.startswith("__"):
            continue
        kid = k["id"]
        yield {
            "id": kid,
            "label": label,
            "title": k.get("title"),
            "type": k["type"],
            "module": k.get("module"),
            "content": k.get("content", ""),
            "prior": priors.get(kid),
            "belief": beliefs.get(kid),
            "exported": kid in exported,
            "metadata": k.get("metadata", {}),
        }

    for i, s in enumerate(ir.get("strategies", [])):
        conc = s.get("conclusion")
        conc_mod = kid_module.get(conc, "") if conc else ""
        yield {
            "id": f"strat_{i}",
            "type": "strategy",
            "strategy_type": s.get("type", ""),
            "module": conc_mod,
            "reason": s.get("reason", ""),
        }

    for i, o in enumerate(ir.get("operators", [])):
        conc = o.get("conclusion")
        conc_mod = kid_module.get(conc, "") if conc else ""
        yield {
            "id": f"oper_{i}",
            "type": "operator",
            "operator_type": o.get("operator", ""),
            "module": conc_mod,
        }


def _iter_edges(ir: dict) -> Iterator[dict]:
    for i, s in enumerate(ir.get("strategies", [])):
        conc = s.get("conclusion")
        if not conc:
            continue
        strat_id = f"strat_{i}"
        for p in s.get("premises", []):
            yield {"source": p, "target": strat_id, "role": "premise"}
        for bg in s.get("background", []):
            yield {"source": bg, "target": strat_id, "role": "background"}
        yield {"source": strat_id, "target": conc, "role": "conclusion"}

    for i, o in enumerate(ir.get("operators", [])):
        conc = o.get("conclusion")
        oper_id = f"oper_{i}"
        for v in o.get("variables", []):
            yield {"source": v, "target": oper_id, "role": "variable"}
        if conc:
            yield {"source": oper_id, "target": conc, "role": "conclusion"}


def _iter_json_array(items: Iterable[dict]) -> Iterator[str]:
    yield "["
    first = True
    for item in items:
        if first:
            first = False
        else:
            yield ","
        yield json.dumps(item, ensure_ascii=False, separators=(",", ":"))
    yield "]"


def iter_graph_json_chunks(
    ir: dict,
    beliefs_data: dict | None = None,
    param_data: dict | None = None,
    exported_ids: set[str] | None = None,
) -> Iterator[str]:
    """Yield graph.json chunks without materializing node/edge arrays."""
    beliefs, priors, exported, kid_module, modules, cross_module_edges = _graph_context(
        ir,
        beliefs_data=beliefs_data,
        param_data=param_data,
        exported_ids=exported_ids,
    )

    yield '{"modules":'
    yield from _iter_json_array(modules)
    yield ',"cross_module_edges":'
    yield from _iter_json_array(cross_module_edges)
    yield ',"nodes":'
    yield from _iter_json_array(_iter_nodes(ir, beliefs, priors, exported, kid_module))
    yield ',"edges":'
    yield from _iter_json_array(_iter_edges(ir))
    yield "}"


def write_graph_json(
    path: Path,
    ir: dict,
    beliefs_data: dict | None = None,
    param_data: dict | None = None,
    exported_ids: set[str] | None = None,
) -> None:
    """Write graph.json directly to *path* using a bounded-memory stream."""
    with path.open("w", encoding="utf-8") as f:
        for chunk in iter_graph_json_chunks(
            ir,
            beliefs_data=beliefs_data,
            param_data=param_data,
            exported_ids=exported_ids,
        ):
            f.write(chunk)


def generate_graph_json(
    ir: dict,
    beliefs_data: dict | None = None,
    param_data: dict | None = None,
    exported_ids: set[str] | None = None,
) -> str:
    """Return JSON string with nodes, edges, modules, and cross_module_edges."""
    return "".join(
        iter_graph_json_chunks(
            ir,
            beliefs_data=beliefs_data,
            param_data=param_data,
            exported_ids=exported_ids,
        )
    )
