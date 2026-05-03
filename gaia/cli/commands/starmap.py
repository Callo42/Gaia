"""gaia starmap — emit an interactive single-file HTML starmap of a compiled package."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from gaia.cli._packages import (
    GaiaCliError,
    apply_package_priors,
    compile_loaded_package_artifact,
    load_gaia_package,
)
from gaia.cli.commands._graph_json import generate_graph_json
from gaia.cli.commands._render_priors import param_data_from_ir_metadata
from gaia.ir.validator import validate_local_graph

GRAPH_DATA_PLACEHOLDER = "<!--__GRAPH_DATA__-->"


def _load_template() -> str:
    """Read the placeholder HTML template that ships with the CLI package."""
    import gaia.cli.starmap_assets as assets_pkg

    template_path = Path(assets_pkg.__file__).parent / "template.html"
    return template_path.read_text(encoding="utf-8")


def _render_html(template: str, graph_json: str) -> str:
    """Inject the graph JSON payload into *template* at the placeholder."""
    if GRAPH_DATA_PLACEHOLDER not in template:
        raise GaiaCliError(
            f"Error: starmap template is missing the {GRAPH_DATA_PLACEHOLDER!r} placeholder."
        )
    injection = f"<script>window.GRAPH_DATA = {graph_json};</script>"
    return template.replace(GRAPH_DATA_PLACEHOLDER, injection, 1)


def starmap_command(
    path: str = typer.Argument(".", help="Path to knowledge package directory"),
    out: str = typer.Option(
        ".gaia/starmap.html",
        "--out",
        help=(
            "Output HTML file. Defaults to '.gaia/starmap.html' relative to the "
            "package directory; absolute paths are honored as-is."
        ),
    ),
) -> None:
    """Emit a single-file interactive HTML starmap of the compiled package.

    The command compiles the package (same gate as `gaia render`), loads
    inferred beliefs and priors when available (degrades gracefully when
    they are not), serializes the graph to JSON via the shared
    `_graph_json` helper, and injects it into a single-file HTML
    template. The result opens in any browser without a server.
    """
    try:
        loaded = load_gaia_package(path)
        apply_package_priors(loaded)
        compiled = compile_loaded_package_artifact(loaded)
    except GaiaCliError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)

    graph_validation = validate_local_graph(compiled.graph)
    for warning in graph_validation.warnings:
        typer.echo(f"Warning: {warning}")
    if graph_validation.errors:
        for error in graph_validation.errors:
            typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1)

    ir = compiled.to_json()

    # Same compile-artifact freshness gate as `render`.
    gaia_dir = loaded.pkg_path / ".gaia"
    ir_hash_path = gaia_dir / "ir_hash"
    ir_json_path = gaia_dir / "ir.json"
    if not ir_hash_path.exists() or not ir_json_path.exists():
        typer.echo("Error: missing compiled artifacts; run `gaia compile` first.", err=True)
        raise typer.Exit(1)
    if ir_hash_path.read_text().strip() != compiled.graph.ir_hash:
        typer.echo("Error: compiled artifacts are stale; run `gaia compile` again.", err=True)
        raise typer.Exit(1)
    try:
        stored_ir = json.loads(ir_json_path.read_text())
    except json.JSONDecodeError as exc:
        typer.echo(f"Error: .gaia/ir.json is not valid JSON: {exc}", err=True)
        raise typer.Exit(1)
    if stored_ir.get("ir_hash") != compiled.graph.ir_hash or stored_ir != ir:
        typer.echo("Error: compiled artifacts are stale; run `gaia compile` again.", err=True)
        raise typer.Exit(1)

    # Beliefs are optional — degrade gracefully when absent. When present they
    # MUST be fresh, mirroring `render`.
    beliefs_data: dict | None = None
    beliefs_path = gaia_dir / "beliefs.json"
    if beliefs_path.exists():
        try:
            beliefs_data = json.loads(beliefs_path.read_text())
        except json.JSONDecodeError as exc:
            typer.echo(f"Error: {beliefs_path} is not valid JSON: {exc}", err=True)
            raise typer.Exit(1)
        if beliefs_data.get("ir_hash") != compiled.graph.ir_hash:
            typer.echo(
                "Error: beliefs are stale; run `gaia infer` again.",
                err=True,
            )
            raise typer.Exit(1)

    param_data = param_data_from_ir_metadata(ir)
    exported_ids = {k["id"] for k in ir.get("knowledges", []) if k.get("exported")}

    graph_json = generate_graph_json(
        ir,
        beliefs_data=beliefs_data,
        param_data=param_data,
        exported_ids=exported_ids,
    )

    try:
        template = _load_template()
        html = _render_html(template, graph_json)
    except GaiaCliError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)

    out_path = Path(out)
    if not out_path.is_absolute():
        out_path = loaded.pkg_path / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    payload = json.loads(graph_json)
    node_count = len(payload.get("nodes", []))
    edge_count = len(payload.get("edges", []))
    typer.echo(f"Wrote starmap to {out_path} ({node_count} nodes, {edge_count} edges)")
