# LKM Explore Artifact MVP Implementation Plan

> **For implementers:** Execute this plan task-by-task. Steps use checkbox
> (`- [ ]`) syntax for tracking. Keep the implementation test-driven, make
> small commits, and preserve backward compatibility for the existing
> `gaia-lkm-explore` commands.

**Goal:** Add typed Explore sidecar artifacts to `gaia-lkm-explore`: `scope`, `focuses`, `artifact`, and `gate`, without breaking the existing frontier-driven exploration loop.

**Architecture:** Add a small deterministic artifact layer under `gaia.lkm_explorer.engine`, then expose it through thin Typer verbs in `gaia.lkm_explorer.client.verbs` and register them in `gaia.lkm_explorer.client.cli`. The MVP writes additive JSON sidecars under `.gaia/exploration/`; existing map, landscape, frontier, turn, and round semantics remain unchanged.

**Tech Stack:** Python 3.12, Typer, dataclasses, JSON sidecar artifacts, pytest.

**Spec reference:** `docs/specs/2026-05-26-lkm-explore-artifact-mvp-design.md`

---

## Plan Code Policy

Code snippets in this plan are illustrative implementation sketches, not a
requirement to paste verbatim. The tests, artifact contracts, command names,
paths, side effects, and compatibility rules are normative. If production code
diverges from a snippet while satisfying the tests and contracts, prefer the
cleaner production code.

## File Structure

Create:

```text
gaia/lkm_explorer/engine/artifacts.py
tests/lkm_explorer/test_artifacts.py
```

Modify:

```text
gaia/lkm_explorer/client/cli.py
gaia/lkm_explorer/client/verbs.py
tests/lkm_explorer/test_cli_explore.py
```

Responsibilities:

- `engine/artifacts.py`: pure artifact builders, dimension parsing, latest landscape discovery, gate checks.
- `client/verbs.py`: Typer command wrappers, file reading/writing, user-facing text.
- `client/cli.py`: command registration.
- `tests/lkm_explorer/test_artifacts.py`: pure engine tests.
- `tests/lkm_explorer/test_cli_explore.py`: CLI smoke and backward-compatibility tests.

## Task 1: Add artifact engine primitives

**Files:**
- Create: `gaia/lkm_explorer/engine/artifacts.py`
- Test: `tests/lkm_explorer/test_artifacts.py`

- [ ] **Step 1: Write failing tests for dimension parsing and UTC ids**

Add tests:

```python
from gaia.lkm_explorer.engine.artifacts import (
    artifact_id,
    parse_dimensions,
)


def test_parse_dimensions_groups_repeated_keys():
    assert parse_dimensions(["population=adults", "outcome=MI", "outcome=bleeding"]) == {
        "population": ["adults"],
        "outcome": ["MI", "bleeding"],
    }


def test_parse_dimensions_rejects_missing_equals():
    try:
        parse_dimensions(["population"])
    except ValueError as exc:
        assert "expected key=value" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_artifact_id_is_readable_and_prefixed():
    value = artifact_id("scope")
    assert value.startswith("scope-")
    assert value.endswith("Z")
```

Run:

```bash
uv run python -m pytest -q tests/lkm_explorer/test_artifacts.py
```

Expected: fail because `gaia.lkm_explorer.engine.artifacts` does not exist.

- [ ] **Step 2: Implement helpers**

Create `gaia/lkm_explorer/engine/artifacts.py`:

```python
"""Typed Explore sidecar artifacts for ``gaia-lkm-explore``.

This module is deterministic and I/O-free except for helpers that inspect
artifact paths. It does not call LKM, author Gaia source, or run inference.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SOP_SCHEMA = "gaia.sop.artifact.v1"


def utcnow() -> str:
    """Return an ISO-8601 UTC timestamp with a trailing ``Z``."""
    return datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def artifact_id(prefix: str) -> str:
    """Return a human-readable timestamp id for an artifact."""
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}"


def parse_dimensions(items: list[str] | None) -> dict[str, list[str]]:
    """Parse repeated ``key=value`` CLI values into grouped dimension lists."""
    out: dict[str, list[str]] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"expected key=value dimension, got {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise ValueError(f"expected non-empty key=value dimension, got {item!r}")
        out.setdefault(key, []).append(value)
    return out


def exploration_dir(pkg: str | Path) -> Path:
    """Return ``<pkg>/.gaia/exploration``."""
    return Path(pkg).resolve() / ".gaia" / "exploration"


def latest_landscape_path(pkg: str | Path) -> Path | None:
    """Return the latest round-numbered landscape artifact, if any."""
    root = exploration_dir(pkg)
    candidates = sorted(root.glob("landscape-*.json"))
    return candidates[-1] if candidates else None


def rel_artifact_path(pkg: str | Path, path: Path | None) -> str | None:
    """Return a package-relative artifact path for stable JSON output."""
    if path is None:
        return None
    pkg_root = Path(pkg).resolve()
    try:
        return str(path.resolve().relative_to(pkg_root))
    except ValueError:
        return str(path)
```

- [ ] **Step 3: Run helper tests**

Run:

```bash
uv run python -m pytest -q tests/lkm_explorer/test_artifacts.py
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add gaia/lkm_explorer/engine/artifacts.py tests/lkm_explorer/test_artifacts.py
git commit -m "feat(lkm-explorer): add explore artifact helpers"
```

## Task 2: Add `scope` artifact builder and CLI

**Files:**
- Modify: `gaia/lkm_explorer/engine/artifacts.py`
- Modify: `gaia/lkm_explorer/client/verbs.py`
- Modify: `gaia/lkm_explorer/client/cli.py`
- Test: `tests/lkm_explorer/test_artifacts.py`
- Test: `tests/lkm_explorer/test_cli_explore.py`

- [ ] **Step 1: Write failing engine test**

Add to `tests/lkm_explorer/test_artifacts.py`:

```python
from gaia.lkm_explorer.engine.artifacts import build_scope_artifact


def test_build_scope_artifact_records_inputs(tmp_path):
    pkg = tmp_path / "pkg"
    (pkg / ".gaia" / "exploration").mkdir(parents=True)

    payload = build_scope_artifact(
        pkg,
        seeds=["aspirin primary prevention"],
        profile="medical",
        dimensions={"outcome": ["MI", "major bleeding"]},
        seed_source="cli",
        map_round=0,
    )

    assert payload["schema"] == "gaia.sop.artifact.v1"
    assert payload["kind"] == "exploration_scope"
    assert payload["inputs"]["seeds"] == ["aspirin primary prevention"]
    assert payload["inputs"]["profile"] == "medical"
    assert payload["inputs"]["dimensions"]["outcome"] == ["MI", "major bleeding"]
    assert payload["audit"]["allowed_next_steps"] == [
        "landscape",
        "focuses",
        "artifact",
        "gate",
    ]
```

Run:

```bash
uv run python -m pytest -q tests/lkm_explorer/test_artifacts.py::test_build_scope_artifact_records_inputs
```

Expected: fail because `build_scope_artifact` does not exist.

- [ ] **Step 2: Implement `build_scope_artifact`**

Add to `engine/artifacts.py`:

```python
def build_scope_artifact(
    pkg: str | Path,
    *,
    seeds: list[str],
    profile: str | None,
    dimensions: dict[str, list[str]],
    seed_source: str,
    map_round: int,
) -> dict[str, Any]:
    """Build the first-class Explore scope artifact."""
    return {
        "schema": SOP_SCHEMA,
        "kind": "exploration_scope",
        "id": artifact_id("scope"),
        "created_at": utcnow(),
        "inputs": {
            "pkg": str(Path(pkg).resolve()),
            "seeds": list(seeds),
            "profile": profile,
            "dimensions": dimensions,
        },
        "artifacts": {
            "map": ".gaia/exploration/map.json",
        },
        "provenance": {
            "seed_source": seed_source,
            "map_round": map_round,
        },
        "audit": {
            "known_limitations": [
                "Scope is user-authored; no automatic domain validation is performed."
            ],
            "allowed_next_steps": ["landscape", "focuses", "artifact", "gate"],
        },
    }
```

- [ ] **Step 3: Write failing CLI test**

Add to `tests/lkm_explorer/test_cli_explore.py` using the existing runner
fixture/pattern in that file:

```python
def test_explore_scope_writes_scope_artifact(galileo_pkg: Path):
    result = runner.invoke(
        explore_app,
        [
            "scope",
            str(galileo_pkg),
            "--seed",
            "free fall",
            "--profile",
            "physics",
            "--dimension",
            "quantity=acceleration",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(
        (galileo_pkg / ".gaia" / "exploration" / "scope.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["kind"] == "exploration_scope"
    assert payload["inputs"]["profile"] == "physics"
    assert payload["inputs"]["dimensions"] == {"quantity": ["acceleration"]}
```

Run:

```bash
uv run python -m pytest -q tests/lkm_explorer/test_cli_explore.py::test_explore_scope_writes_scope_artifact
```

Expected: fail because command is not registered.

- [ ] **Step 4: Implement `scope_command` and register it**

In `client/verbs.py`, import:

```python
from gaia.engine.packaging import write_text_atomic
from gaia.lkm_explorer.engine.artifacts import (
    build_scope_artifact,
    parse_dimensions,
)
```

Add option singletons:

```python
_SCOPE_SEED_OPT = typer.Option(
    None,
    "--seed",
    help="Seed text for the exploration scope (repeatable; defaults to map seeds).",
)
_SCOPE_PROFILE_OPT = typer.Option(None, "--profile", help="Optional domain profile.")
_SCOPE_DIMENSION_OPT = typer.Option(
    None,
    "--dimension",
    help="Scope dimension as key=value (repeatable).",
)
_SCOPE_OUT_OPT = typer.Option(
    None,
    "--out",
    help="Output JSON path (default <pkg>/.gaia/exploration/scope.json).",
)
```

Add command:

```python
def scope_command(
    pkg: str = _PKG_ARG,
    seed: list[str] | None = _SCOPE_SEED_OPT,
    profile: str | None = _SCOPE_PROFILE_OPT,
    dimension: list[str] | None = _SCOPE_DIMENSION_OPT,
    out: str | None = _SCOPE_OUT_OPT,
    json_out: bool = _LANDSCAPE_JSON_OPT,
) -> None:
    """Write a first-class exploration scope sidecar."""
    if not (_gaia_dir(pkg) / "exploration" / "map.json").exists():
        typer.echo(
            f"Error: no exploration map at {pkg}; run `gaia-lkm-explore init` first.",
            err=True,
        )
        raise typer.Exit(1)
    exploration_map = load_map(pkg)
    seeds = list(seed or [])
    seed_source = "cli"
    if not seeds:
        seeds = [str(s.get("raw", s.get("qid", ""))) for s in exploration_map.seeds]
        seeds = [s for s in seeds if s]
        seed_source = "map"
    try:
        dimensions = parse_dimensions(dimension)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    payload = build_scope_artifact(
        pkg,
        seeds=seeds,
        profile=profile,
        dimensions=dimensions,
        seed_source=seed_source,
        map_round=exploration_map.round,
    )
    output_path = Path(out) if out is not None else _gaia_dir(pkg) / "exploration" / "scope.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(output_path, json.dumps(payload, ensure_ascii=False, indent=2))
    typer.echo(f"Scope: {len(seeds)} seed(s), {len(dimensions)} dimension group(s).")
    typer.echo(f"Output: {output_path}")
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
```

In `client/cli.py`, import and register:

```python
from gaia.lkm_explorer.client.verbs import scope_command

app.command(name="scope")(scope_command)
```

- [ ] **Step 5: Run CLI test**

Run:

```bash
uv run python -m pytest -q tests/lkm_explorer/test_cli_explore.py::test_explore_scope_writes_scope_artifact
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add gaia/lkm_explorer/engine/artifacts.py gaia/lkm_explorer/client/verbs.py gaia/lkm_explorer/client/cli.py tests/lkm_explorer/test_artifacts.py tests/lkm_explorer/test_cli_explore.py
git commit -m "feat(lkm-explorer): add scope artifact command"
```

## Task 3: Add deterministic `focuses`

**Files:**
- Modify: `gaia/lkm_explorer/engine/artifacts.py`
- Modify: `gaia/lkm_explorer/client/verbs.py`
- Modify: `gaia/lkm_explorer/client/cli.py`
- Test: `tests/lkm_explorer/test_artifacts.py`
- Test: `tests/lkm_explorer/test_cli_explore.py`

- [ ] **Step 1: Write failing engine test for landscape focus generation**

Add:

```python
from gaia.lkm_explorer.engine.artifacts import build_focuses_artifact


def test_build_focuses_artifact_uses_landscape_paper_leads(tmp_path):
    pkg = tmp_path / "pkg"
    landscape_path = pkg / ".gaia" / "exploration" / "landscape-0.json"
    landscape_path.parent.mkdir(parents=True)
    landscape_path.write_text(
        json.dumps(
            {
                "kind": "exploration_landscape",
                "paper_leads": [
                    {"paper_id": "P1", "title": "Paper One"},
                    {"paper_id": "P2", "title": "Paper Two"},
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = build_focuses_artifact(
        pkg,
        scope_path=None,
        landscape_path=landscape_path,
        landscape={"kind": "exploration_landscape", "paper_leads": [{"paper_id": "P1"}]},
        map_round=0,
    )

    assert payload["kind"] == "exploration_focuses"
    assert payload["focuses"][0]["kind"] == "paper_lead_cluster"
    assert payload["focuses"][0]["evidence_refs"][0]["paper_id"] == "P1"
```

- [ ] **Step 2: Implement `build_focuses_artifact`**

Add:

```python
def build_focuses_artifact(
    pkg: str | Path,
    *,
    scope_path: Path | None,
    landscape_path: Path | None,
    landscape: dict[str, Any] | None,
    map_round: int,
) -> dict[str, Any]:
    """Build deterministic, provenance-backed assessment focuses."""
    focuses: list[dict[str, Any]] = []
    leads = []
    if landscape:
        raw_leads = landscape.get("paper_leads")
        if isinstance(raw_leads, list):
            leads = [lead for lead in raw_leads if isinstance(lead, dict)]
    if leads:
        refs = []
        for lead in leads[:5]:
            paper_id = lead.get("paper_id")
            if isinstance(paper_id, str) and paper_id:
                refs.append(
                    {
                        "kind": "landscape_paper_lead",
                        "path": rel_artifact_path(pkg, landscape_path),
                        "paper_id": paper_id,
                    }
                )
        if refs:
            focuses.append(
                {
                    "id": "focus_landscape_top_leads",
                    "kind": "paper_lead_cluster",
                    "text": "Top unpulled paper leads from the current landscape",
                    "why_it_matters": (
                        "These papers are the highest-ranked breadth-first leads "
                        "and should be considered before local claim-level expansion."
                    ),
                    "evidence_refs": refs,
                    "recommended_next": "assess",
                    "confidence": "structural",
                }
            )
    return {
        "schema": SOP_SCHEMA,
        "kind": "exploration_focuses",
        "id": artifact_id("focuses"),
        "created_at": utcnow(),
        "inputs": {
            "pkg": str(Path(pkg).resolve()),
            "scope": rel_artifact_path(pkg, scope_path),
            "landscape": rel_artifact_path(pkg, landscape_path),
        },
        "artifacts": {
            "map": ".gaia/exploration/map.json",
            "landscape": rel_artifact_path(pkg, landscape_path),
        },
        "focuses": focuses,
        "provenance": {"generation": "deterministic", "map_round": map_round},
        "audit": {
            "known_limitations": [
                "MVP focuses are structural and provenance-backed; domain-specific tension naming is external or future work."
            ],
            "allowed_next_steps": ["artifact", "gate"],
        },
    }
```

- [ ] **Step 3: Add CLI command and registration**

Add `focuses_command` in `verbs.py`:

```python
def focuses_command(
    pkg: str = _PKG_ARG,
    landscape: str | None = typer.Option(
        None,
        "--landscape",
        help="Landscape JSON path (default latest <pkg>/.gaia/exploration/landscape-*.json).",
    ),
    out: str | None = typer.Option(
        None,
        "--out",
        help="Output JSON path (default <pkg>/.gaia/exploration/focuses.json).",
    ),
    json_out: bool = _LANDSCAPE_JSON_OPT,
) -> None:
    """Write deterministic assessment focuses from the latest landscape."""
```

Implementation details:

- load map with `load_map(pkg)`;
- resolve `landscape_path = Path(landscape)` if provided else `latest_landscape_path(pkg)`;
- if no landscape path exists, emit error and exit 2;
- read landscape JSON with `_read_json_object`;
- `scope_path = _gaia_dir(pkg) / "exploration" / "scope.json"` if exists else `None`;
- write `.gaia/exploration/focuses.json`.

Register in `client/cli.py`:

```python
app.command(name="focuses")(focuses_command)
```

- [ ] **Step 4: Add CLI test**

Add:

```python
def test_explore_focuses_writes_focuses_from_landscape(galileo_pkg: Path):
    landscape_path = galileo_pkg / ".gaia" / "exploration" / "landscape-0.json"
    landscape_path.write_text(
        json.dumps(
            {
                "kind": "exploration_landscape",
                "paper_leads": [{"paper_id": "P1", "title": "Paper One"}],
            }
        ),
        encoding="utf-8",
    )
    result = runner.invoke(explore_app, ["focuses", str(galileo_pkg)])

    assert result.exit_code == 0, result.output
    payload = json.loads(
        (galileo_pkg / ".gaia" / "exploration" / "focuses.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["kind"] == "exploration_focuses"
    assert payload["focuses"][0]["id"] == "focus_landscape_top_leads"
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
uv run python -m pytest -q tests/lkm_explorer/test_artifacts.py tests/lkm_explorer/test_cli_explore.py::test_explore_focuses_writes_focuses_from_landscape
```

Commit:

```bash
git add gaia/lkm_explorer/engine/artifacts.py gaia/lkm_explorer/client/verbs.py gaia/lkm_explorer/client/cli.py tests/lkm_explorer/test_artifacts.py tests/lkm_explorer/test_cli_explore.py
git commit -m "feat(lkm-explorer): add focuses artifact command"
```

## Task 4: Add `artifact` envelope

**Files:**
- Modify: `gaia/lkm_explorer/engine/artifacts.py`
- Modify: `gaia/lkm_explorer/client/verbs.py`
- Modify: `gaia/lkm_explorer/client/cli.py`
- Test: `tests/lkm_explorer/test_artifacts.py`
- Test: `tests/lkm_explorer/test_cli_explore.py`

- [ ] **Step 1: Write failing test for missing optional files**

Add:

```python
from gaia.lkm_explorer.engine.artifacts import build_exploration_artifact


def test_build_exploration_artifact_records_missing_optional_files(tmp_path):
    pkg = tmp_path / "pkg"
    (pkg / ".gaia" / "exploration").mkdir(parents=True)

    payload = build_exploration_artifact(pkg, map_round=0, map_version=1)

    assert payload["kind"] == "lkm_exploration"
    assert payload["artifacts"]["scope"] is None
    assert "missing scope" in payload["audit"]["known_limitations"]
    assert payload["audit"]["allowed_next_steps"] == ["gate"]
```

- [ ] **Step 2: Implement `build_exploration_artifact`**

Add:

```python
def _maybe_rel(pkg: str | Path, path: Path) -> str | None:
    return rel_artifact_path(pkg, path) if path.exists() else None


def build_exploration_artifact(
    pkg: str | Path,
    *,
    map_round: int,
    map_version: int,
) -> dict[str, Any]:
    """Aggregate Explore sidecars into a single handoff envelope."""
    root = exploration_dir(pkg)
    scope = root / "scope.json"
    landscape = latest_landscape_path(pkg)
    focuses = root / "focuses.json"
    map_path = root / "map.json"
    rounds = root / "rounds.jsonl"
    gaia_dir = Path(pkg).resolve() / ".gaia"
    ir = gaia_dir / "ir.json"
    beliefs = gaia_dir / "beliefs.json"
    limitations = []
    for label, path in [
        ("scope", scope),
        ("landscape", landscape),
        ("focuses", focuses),
        ("map", map_path),
    ]:
        if path is None or not path.exists():
            limitations.append(f"missing {label}")
    return {
        "schema": SOP_SCHEMA,
        "kind": "lkm_exploration",
        "id": artifact_id("explore"),
        "created_at": utcnow(),
        "inputs": {"pkg": str(Path(pkg).resolve())},
        "artifacts": {
            "scope": _maybe_rel(pkg, scope),
            "landscape": rel_artifact_path(pkg, landscape) if landscape else None,
            "focuses": _maybe_rel(pkg, focuses),
            "map": _maybe_rel(pkg, map_path),
            "rounds": _maybe_rel(pkg, rounds),
            "gaia_ir": _maybe_rel(pkg, ir),
            "beliefs": _maybe_rel(pkg, beliefs),
        },
        "provenance": {
            "map_round": map_round,
            "map_version": map_version,
        },
        "audit": {
            "coverage": {},
            "known_limitations": limitations,
            "allowed_next_steps": ["gate"],
        },
        "interface": {
            "assess": {
                "command": (
                    "gaia-evidence assess --exploration "
                    ".gaia/exploration/artifact.json --focus <focus-id>"
                )
            }
        },
    }
```

- [ ] **Step 3: Add CLI command and test**

Add `artifact_command` analogous to `focuses_command`:

- load `ExplorationMap`;
- call `build_exploration_artifact(pkg, map_round=exploration_map.round, map_version=exploration_map.version)`;
- write `.gaia/exploration/artifact.json`;
- print output path and limitation count.

Register `app.command(name="artifact")(artifact_command)`.

CLI test:

```python
def test_explore_artifact_writes_handoff_envelope(galileo_pkg: Path):
    result = runner.invoke(explore_app, ["artifact", str(galileo_pkg)])

    assert result.exit_code == 0, result.output
    payload = json.loads(
        (galileo_pkg / ".gaia" / "exploration" / "artifact.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["kind"] == "lkm_exploration"
    assert payload["interface"]["assess"]["command"].startswith("gaia-evidence assess")
```

- [ ] **Step 4: Run tests and commit**

Run:

```bash
uv run python -m pytest -q tests/lkm_explorer/test_artifacts.py tests/lkm_explorer/test_cli_explore.py::test_explore_artifact_writes_handoff_envelope
```

Commit:

```bash
git add gaia/lkm_explorer/engine/artifacts.py gaia/lkm_explorer/client/verbs.py gaia/lkm_explorer/client/cli.py tests/lkm_explorer/test_artifacts.py tests/lkm_explorer/test_cli_explore.py
git commit -m "feat(lkm-explorer): add exploration artifact envelope"
```

## Task 5: Add deterministic Explore gate

**Files:**
- Modify: `gaia/lkm_explorer/engine/artifacts.py`
- Modify: `gaia/lkm_explorer/client/verbs.py`
- Modify: `gaia/lkm_explorer/client/cli.py`
- Test: `tests/lkm_explorer/test_artifacts.py`
- Test: `tests/lkm_explorer/test_cli_explore.py`

- [ ] **Step 1: Write failing gate tests**

Add:

```python
from gaia.lkm_explorer.engine.artifacts import build_gate_report


def test_gate_blocks_without_focuses():
    artifact = {
        "schema": "gaia.sop.artifact.v1",
        "kind": "lkm_exploration",
        "artifacts": {
            "scope": ".gaia/exploration/scope.json",
            "landscape": ".gaia/exploration/landscape-0.json",
            "focuses": None,
            "map": ".gaia/exploration/map.json",
            "artifact": ".gaia/exploration/artifact.json",
        },
    }

    report = build_gate_report(artifact, focuses=None)

    assert report["verdict"] == "block"
    assert "assess" not in report["allowed_next_steps"]


def test_gate_passes_with_evidence_backed_focus():
    artifact = {
        "schema": "gaia.sop.artifact.v1",
        "kind": "lkm_exploration",
        "artifacts": {
            "scope": ".gaia/exploration/scope.json",
            "landscape": ".gaia/exploration/landscape-0.json",
            "focuses": ".gaia/exploration/focuses.json",
            "map": ".gaia/exploration/map.json",
            "artifact": ".gaia/exploration/artifact.json",
            "gaia_ir": ".gaia/ir.json",
            "beliefs": ".gaia/beliefs.json",
            "rounds": ".gaia/exploration/rounds.jsonl",
        },
    }
    focuses = {"focuses": [{"id": "f1", "evidence_refs": [{"kind": "x"}]}]}

    report = build_gate_report(artifact, focuses=focuses)

    assert report["verdict"] == "pass"
    assert report["allowed_next_steps"] == ["assess"]


def test_gate_revises_when_optional_graph_artifacts_are_missing():
    artifact = {
        "schema": "gaia.sop.artifact.v1",
        "kind": "lkm_exploration",
        "artifacts": {
            "scope": ".gaia/exploration/scope.json",
            "landscape": ".gaia/exploration/landscape-0.json",
            "focuses": ".gaia/exploration/focuses.json",
            "map": ".gaia/exploration/map.json",
            "artifact": ".gaia/exploration/artifact.json",
            "gaia_ir": None,
            "beliefs": None,
            "rounds": None,
        },
    }
    focuses = {"focuses": [{"id": "f1", "evidence_refs": [{"kind": "x"}]}]}

    report = build_gate_report(artifact, focuses=focuses)

    assert report["verdict"] == "revise"
    assert report["allowed_next_steps"] == []
    assert any(
        c["id"] == "compiled_ir_present" and c["status"] == "warn"
        for c in report["checks"]
    )
```

- [ ] **Step 2: Implement `build_gate_report`**

Add:

```python
def _check(status: str, check_id: str, finding: str) -> dict[str, str]:
    return {"id": check_id, "status": status, "finding": finding}


def build_gate_report(
    artifact: dict[str, Any],
    *,
    focuses: dict[str, Any] | None,
) -> dict[str, Any]:
    """Check whether an Explore artifact is structurally ready for Assess."""
    checks = []
    artifacts = artifact.get("artifacts", {}) if isinstance(artifact, dict) else {}

    schema_ok = artifact.get("schema") == SOP_SCHEMA
    checks.append(
        _check(
            "pass" if schema_ok else "fail",
            "schema_versions_supported",
            "schema supported"
            if schema_ok
            else f"unsupported schema: {artifact.get('schema')!r}",
        )
    )

    for key in ["scope", "landscape", "focuses", "map", "artifact"]:
        present = bool(artifacts.get(key))
        checks.append(
            _check(
                "pass" if present else "fail",
                f"{key}_present",
                f"{key} {'present' if present else 'missing'}",
            )
        )

    for key, check_id in [
        ("gaia_ir", "compiled_ir_present"),
        ("beliefs", "beliefs_present"),
        ("rounds", "rounds_present"),
    ]:
        present = bool(artifacts.get(key))
        checks.append(
            _check(
                "pass" if present else "warn",
                check_id,
                f"{key} {'present' if present else 'missing'}",
            )
        )

    focus_rows = []
    if isinstance(focuses, dict) and isinstance(focuses.get("focuses"), list):
        focus_rows = [f for f in focuses["focuses"] if isinstance(f, dict)]
    checks.append(
        _check(
            "pass" if focus_rows else "fail",
            "has_assessable_focus",
            f"{len(focus_rows)} focus(es) available.",
        )
    )
    missing_refs = [f.get("id", "<unknown>") for f in focus_rows if not f.get("evidence_refs")]
    checks.append(
        _check(
            "pass" if not missing_refs and focus_rows else "warn",
            "focuses_have_evidence_refs",
            "All focuses include evidence_refs." if not missing_refs and focus_rows else f"Missing refs: {missing_refs}",
        )
    )
    failed = [c for c in checks if c["status"] == "fail"]
    warned = [c for c in checks if c["status"] == "warn"]
    if failed:
        verdict = "block"
    elif warned:
        verdict = "revise"
    else:
        verdict = "pass"
    return {
        "schema": SOP_SCHEMA,
        "kind": "quality_gate_report",
        "id": artifact_id("explore-gate"),
        "created_at": utcnow(),
        "target_kind": "lkm_exploration",
        "target": ".gaia/exploration/artifact.json",
        "verdict": verdict,
        "checks": checks,
        "required_changes": [c["finding"] for c in failed],
        "allowed_next_steps": ["assess"] if verdict == "pass" else [],
    }
```

- [ ] **Step 3: Add CLI command**

Add `gate_command`:

- read `.gaia/exploration/artifact.json`, or build and write it if missing;
- read `.gaia/exploration/focuses.json` when present;
- call `build_gate_report`;
- write `.gaia/exploration/gate_report.json`;
- print `Gate: pass|revise|block`;
- return exit code 0 for `pass` and `revise`;
- raise `typer.Exit(1)` when verdict is `block`.

Register:

```python
app.command(name="gate")(gate_command)
```

- [ ] **Step 4: Add CLI test**

Add:

```python
def test_explore_gate_blocks_without_focuses(galileo_pkg: Path):
    runner.invoke(explore_app, ["artifact", str(galileo_pkg)])

    result = runner.invoke(explore_app, ["gate", str(galileo_pkg)])

    assert result.exit_code == 1
    payload = json.loads(
        (galileo_pkg / ".gaia" / "exploration" / "gate_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["verdict"] == "block"
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
uv run python -m pytest -q tests/lkm_explorer/test_artifacts.py tests/lkm_explorer/test_cli_explore.py::test_explore_gate_blocks_without_focuses
```

Commit:

```bash
git add gaia/lkm_explorer/engine/artifacts.py gaia/lkm_explorer/client/verbs.py gaia/lkm_explorer/client/cli.py tests/lkm_explorer/test_artifacts.py tests/lkm_explorer/test_cli_explore.py
git commit -m "feat(lkm-explorer): add explore gate report"
```

## Task 6: Backward compatibility and help surface

**Files:**
- Modify: `tests/lkm_explorer/test_cli_explore.py`
- Modify: `gaia/lkm_explorer/client/cli.py`

- [ ] **Step 1: Add CLI help test**

Add:

```python
def test_explore_cli_lists_artifact_mvp_commands():
    result = runner.invoke(explore_app, ["--help"])

    assert result.exit_code == 0
    assert "scope" in result.output
    assert "focuses" in result.output
    assert "artifact" in result.output
    assert "gate" in result.output
    assert "turn" in result.output
```

- [ ] **Step 2: Ensure command registration order is readable**

In `client/cli.py`, register commands in this order:

```python
app.command(name="init")(init_command)
app.command(name="scope")(scope_command)
app.command(name="observe")(observe_command)
app.command(name="landscape")(landscape_command)
app.command(name="focuses")(focuses_command)
app.command(name="artifact")(artifact_command)
app.command(name="gate")(gate_command)
app.command(name="frontier")(frontier_command)
app.command(name="round")(round_command)
app.command(name="status")(status_command)
app.command(name="render")(render_command)
```

Keep `turn` registered below as it is today.

- [ ] **Step 3: Run compatibility tests**

Run:

```bash
uv run python -m pytest -q tests/lkm_explorer/test_landscape.py tests/lkm_explorer/test_cli_explore.py tests/lkm_explorer/test_frontier.py tests/lkm_explorer/test_orchestrator.py
```

Expected: all pass. Existing `landscape`, `frontier`, and `turn` behavior still works.

- [ ] **Step 4: Commit**

```bash
git add gaia/lkm_explorer/client/cli.py tests/lkm_explorer/test_cli_explore.py
git commit -m "test(lkm-explorer): cover artifact mvp cli surface"
```

## Task 7: Final verification

**Files:**
- No new code unless verification reveals a bug.

- [ ] **Step 1: Run targeted Explore tests**

```bash
uv run python -m pytest -q tests/lkm_explorer/test_artifacts.py tests/lkm_explorer/test_landscape.py tests/lkm_explorer/test_cli_explore.py tests/lkm_explorer/test_frontier.py tests/lkm_explorer/test_orchestrator.py tests/lkm_explorer/test_promote.py
```

Expected: all pass.

- [ ] **Step 2: Run PR gate**

```bash
uv run python -m pytest -q -m "pr_gate and not slow"
```

Expected: all pass. Use `uv run python -m pytest`, not `uv run pytest`, because
the latter may resolve to an external conda pytest in this workspace.

- [ ] **Step 3: Run whitespace check**

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 4: Update docs if command help differs from the spec**

If the implemented command names or paths differ from
`docs/specs/2026-05-26-lkm-explore-artifact-mvp-design.md`, update the spec in
the same PR before final review.

- [ ] **Step 5: Final commit if needed**

```bash
git add docs/specs/2026-05-26-lkm-explore-artifact-mvp-design.md docs/plans/2026-05-26-lkm-explore-artifact-mvp.md
git commit -m "docs(lkm): add explore artifact mvp plan"
```
