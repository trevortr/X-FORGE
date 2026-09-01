from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from app.main import STATIC_ROOT, create_app


def _write_run(results_root: Path, name: str, **updates) -> dict:
    value = {
        "run_id": "run-123",
        "target": "acetaminophen",
        "status": "completed",
        "started_at": "2026-08-30T20:09:12Z",
        "completed_at": "2026-08-30T20:09:29Z",
        "requested_iterations": 3,
        "completed_iterations": 3,
        "initial_seeds": [],
        "iterations": [],
        "molecule_catalog": [],
        **updates,
    }
    directory = results_root / name
    directory.mkdir(parents=True)
    (directory / "run.json").write_text(json.dumps(value), encoding="utf-8")
    return value


async def _get(app, *paths: str) -> list[httpx.Response]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return [await client.get(path) for path in paths]


def test_lists_and_serves_run_results(tmp_path: Path) -> None:
    expected = _write_run(tmp_path, "acetaminophen-run")

    listing, result = asyncio.run(
        _get(create_app(tmp_path), "/api/runs", "/api/runs/acetaminophen-run")
    )

    assert listing.status_code == 200
    assert listing.json()["runs"] == [
        {
            "name": "acetaminophen-run",
            "run_id": "run-123",
            "target": "acetaminophen",
            "status": "completed",
            "started_at": "2026-08-30T20:09:12Z",
            "completed_at": "2026-08-30T20:09:29Z",
            "completed_iterations": 3,
        }
    ]
    assert result.status_code == 200
    assert result.json() == expected
    assert result.headers["cache-control"] == "no-store"


def test_skips_malformed_runs_and_rejects_unsafe_names(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed"
    malformed.mkdir()
    (malformed / "run.json").write_text("not JSON", encoding="utf-8")
    listing, hidden, missing = asyncio.run(
        _get(
            create_app(tmp_path),
            "/api/runs",
            "/api/runs/.hidden",
            "/api/runs/missing",
        )
    )

    assert listing.json() == {"runs": []}
    assert hidden.status_code == 400
    assert missing.status_code == 404


def test_serves_visualizer_shell_and_health(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    health, shell = asyncio.run(_get(app, "/health", "/"))
    index = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")
    route_paths = {route.path for route in app.routes}

    assert "Molecule lineage" in index
    assert "Reveal whole graph" in index
    assert "Show all edges" in index
    assert "Show SMILES labels" in index
    assert "Pan left" in index
    assert "Wider" in index
    assert "Taller" in index
    assert 'aria-keyshortcuts="ArrowRight"' in index
    assert "WASD" in index
    assert "/static/app.js?v=" in index
    assert "/static/styles.css?v=" in index
    assert "Leaf molecule" in index
    assert "Click to expand or collapse" in index
    assert {"/", "/static", "/health"} <= route_paths
    assert (STATIC_ROOT / "app.js").is_file()
    assert 'document.addEventListener("keydown", handleShortcut)' in script
    assert 'arrowleft: () => resizeCanvas("horizontal", -1)' in script
    assert 'arrowdown: () => resizeCanvas("vertical", -1)' in script
    assert '"=": () => setZoom(zoom * 1.25)' in script
    assert "height: 100dvh" in styles
    assert "grid-template-rows: auto minmax(0, 1fr)" in styles
    assert health.json() == {"status": "ok"}
    assert shell.headers["cache-control"] == "no-store"


def test_renders_cached_rdkit_molecule_depiction(tmp_path: Path) -> None:
    valid, invalid = asyncio.run(
        _get(
            create_app(tmp_path),
            "/api/depict?smiles=CCO",
            "/api/depict?smiles=not-a-smiles",
        )
    )

    assert valid.status_code == 200
    assert valid.headers["content-type"].startswith("image/svg+xml")
    assert valid.headers["cache-control"] == "public, max-age=86400"
    assert "<svg" in valid.text
    assert invalid.status_code == 422


def test_graph_endpoint_starts_at_hit_and_expands_children(tmp_path: Path) -> None:
    _write_run(
        tmp_path,
        "lineage-run",
        initial_seeds=[{"id": "hit", "smiles": "CCO", "iteration": 0, "scores": []}],
        iterations=[
            {
                "iteration": 1,
                "generated": [
                    {
                        "id": "child",
                        "parent_id": "hit",
                        "smiles": "CCN",
                        "iteration": 1,
                        "scores": [],
                    }
                ],
            }
        ],
    )
    app = create_app(tmp_path)

    initial, expanded, all_nodes, all_edges, labeled, stretched, collapsed, invalid = asyncio.run(
        _get(
            app,
            "/api/runs/lineage-run/graph",
            "/api/runs/lineage-run/graph?expanded=hit",
            "/api/runs/lineage-run/graph?show_all=true",
            "/api/runs/lineage-run/graph?show_all=true&show_all_edges=true",
            "/api/runs/lineage-run/graph?show_labels=true",
            "/api/runs/lineage-run/graph?horizontal_scale=1.5&vertical_scale=2",
            "/api/runs/lineage-run/graph",
            "/api/runs/lineage-run/graph?expanded=unknown",
        )
    )

    assert initial.status_code == 200
    assert [node["id"] for node in initial.json()["nodes"]] == ["hit"]
    assert initial.json()["visible_count"] == 1
    assert initial.json()["fully_expanded"] is False
    assert {node["id"] for node in expanded.json()["nodes"]} == {"hit", "child"}
    assert expanded.json()["fully_expanded"] is True
    assert {node["id"] for node in all_nodes.json()["nodes"]} == {"hit", "child"}
    assert all_nodes.json()["visible_edge_count"] == 1
    assert all_nodes.json()["total_edge_count"] == 1
    assert all_nodes.json()["fully_expanded"] is True
    assert all_nodes.json()["show_all_edges"] is False
    assert all_edges.json()["show_all_edges"] is True
    assert initial.json()["show_labels"] is False
    assert 'id="label-mol-aGl0"' not in initial.json()["svg"]
    assert labeled.json()["show_labels"] is True
    assert 'id="label-mol-aGl0"' in labeled.json()["svg"]
    assert initial.json()["canvas_width"] > 0
    assert initial.json()["canvas_height"] > 0
    assert stretched.json()["canvas_width"] > initial.json()["canvas_width"]
    assert stretched.json()["canvas_height"] > initial.json()["canvas_height"]
    assert stretched.json()["horizontal_scale"] == 1.5
    assert stretched.json()["vertical_scale"] == 2
    assert [node["id"] for node in collapsed.json()["nodes"]] == ["hit"]
    assert 'id="node-mol-aGl0"' in initial.json()["svg"]
    assert invalid.status_code == 422
