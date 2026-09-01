from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .depiction import MoleculeDepictionError, render_molecule_svg
from .run_graph import MoleculeRunGraph, RunGraphError, render_svg

STATIC_ROOT = Path(__file__).parent / "static"
RUN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _read_run(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read run result: {exc}") from exc
    if not isinstance(value, dict):
        raise TypeError("run result must be a JSON object")
    return value


def create_app(results_root: Path | None = None) -> FastAPI:
    root = Path(results_root or os.getenv("XFORGE_RESULTS_ROOT", "/results")).resolve()
    app = FastAPI(
        title="X-FORGE Run Visualizer",
        version="0.2.0",
        description="Render X-FORGE molecule lineage with NetworkX and Matplotlib.",
    )
    app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")

    def run_file(run_name: str) -> Path:
        if not RUN_NAME.fullmatch(run_name):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid run name",
            )
        path = (root / run_name / "run.json").resolve()
        if not path.is_relative_to(root):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="run path escapes results root",
            )
        return path

    def load_named_run(run_name: str) -> dict[str, Any]:
        path = run_file(run_name)
        if not path.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="run not found",
            )
        try:
            return _read_run(path)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/depict", response_class=Response)
    async def depict_molecule(
        smiles: Annotated[str, Query(min_length=1, max_length=10_000)],
    ) -> Response:
        try:
            svg = render_molecule_svg(smiles)
        except MoleculeDepictionError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        return Response(
            content=svg,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/api/runs")
    async def list_runs() -> dict[str, list[dict[str, Any]]]:
        runs: list[dict[str, Any]] = []
        if root.is_dir():
            for directory in root.iterdir():
                if not directory.is_dir() or not RUN_NAME.fullmatch(directory.name):
                    continue
                try:
                    path = run_file(directory.name)
                except HTTPException:
                    continue
                if not path.is_file():
                    continue
                try:
                    value = _read_run(path)
                except (TypeError, ValueError):
                    continue
                runs.append(
                    {
                        "name": directory.name,
                        "run_id": value.get("run_id"),
                        "target": value.get("target"),
                        "status": value.get("status"),
                        "started_at": value.get("started_at"),
                        "completed_at": value.get("completed_at"),
                        "completed_iterations": value.get("completed_iterations", 0),
                    }
                )
        runs.sort(key=lambda item: item.get("started_at") or "", reverse=True)
        return {"runs": runs}

    @app.get("/api/runs/{run_name}/graph")
    async def get_graph(
        run_name: str,
        expanded: Annotated[list[str] | None, Query()] = None,
        show_all: bool = False,
        show_all_edges: bool = False,
        show_labels: bool = False,
        horizontal_scale: Annotated[float, Query(ge=1.0, le=4.0)] = 1.0,
        vertical_scale: Annotated[float, Query(ge=1.0, le=4.0)] = 1.0,
    ) -> JSONResponse:
        try:
            run_graph = MoleculeRunGraph.from_run(load_named_run(run_name))
            requested = frozenset(expanded or [])
            unknown = requested - run_graph.node_ids
            if unknown:
                raise RunGraphError(
                    f"unknown expanded molecule ID(s): {', '.join(sorted(unknown))}"
                )
            effective_expanded = run_graph.node_ids if show_all else requested
            rendered = render_svg(
                run_graph,
                effective_expanded,
                show_all_edges=show_all_edges,
                show_labels=show_labels,
                horizontal_scale=horizontal_scale,
                vertical_scale=vertical_scale,
            )
        except RunGraphError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        return JSONResponse(rendered, headers={"Cache-Control": "no-store"})

    @app.get("/api/runs/{run_name}")
    async def get_run(run_name: str) -> JSONResponse:
        return JSONResponse(
            load_named_run(run_name), headers={"Cache-Control": "no-store"}
        )

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(
            STATIC_ROOT / "index.html",
            headers={"Cache-Control": "no-store"},
        )

    return app


app = create_app()
