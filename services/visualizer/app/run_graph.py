from __future__ import annotations

import base64
import heapq
import io
import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import matplotlib
import networkx as nx
from matplotlib.backends.backend_svg import FigureCanvasSVG
from matplotlib.figure import Figure

matplotlib.use("svg")

_RENDER_LOCK = threading.Lock()
_COLORS = ("#2563eb", "#7c3aed", "#db2777", "#ea580c", "#0891b2")


class RunGraphError(ValueError):
    pass


def _dom_token(molecule_id: str) -> str:
    encoded = base64.urlsafe_b64encode(molecule_id.encode()).decode().rstrip("=")
    return f"mol-{encoded}"


def _short_label(smiles: str, maximum: int = 24) -> str:
    return smiles if len(smiles) <= maximum else f"{smiles[: maximum - 1]}…"


@dataclass(frozen=True)
class MoleculeRunGraph:
    graph: nx.DiGraph
    molecules: dict[str, dict[str, Any]]
    roots: tuple[str, ...]
    occurrences: dict[str, tuple[int, ...]]
    parents: dict[str, tuple[str, ...]]
    primary_edges: frozenset[tuple[str, str]]
    positions: dict[str, tuple[float, float]]

    @property
    def node_ids(self) -> frozenset[str]:
        return frozenset(self.graph.nodes)

    @classmethod
    def from_run(cls, run: dict[str, Any]) -> MoleculeRunGraph:
        molecules: dict[str, dict[str, Any]] = {}
        occurrences: defaultdict[str, set[int]] = defaultdict(set)
        parent_sets: defaultdict[str, set[str]] = defaultdict(set)
        relation_iterations: dict[tuple[str, str], int] = {}

        def remember(molecule: Any, fallback_iteration: int = 0) -> None:
            if not isinstance(molecule, dict) or not molecule.get("id"):
                return
            molecule_id = str(molecule["id"])
            molecules[molecule_id] = dict(molecule)
            iteration = molecule.get("iteration", fallback_iteration)
            if isinstance(iteration, int) and iteration >= 0:
                occurrences[molecule_id].add(iteration)

        initial_seeds = run.get("initial_seeds", [])
        if not isinstance(initial_seeds, list):
            raise RunGraphError("initial_seeds must be a list")
        for seed in initial_seeds:
            remember(seed, 0)

        iterations = run.get("iterations", [])
        if not isinstance(iterations, list):
            raise RunGraphError("iterations must be a list")
        for iteration in iterations:
            if not isinstance(iteration, dict):
                continue
            iteration_number = iteration.get("iteration", 0)
            for population_name in (
                "seeds",
                "generated",
                "survivors",
                "evaluated",
                "pareto_front",
                "selected",
            ):
                for molecule in iteration.get(population_name, []) or []:
                    remember(molecule, iteration_number)
            for molecule in iteration.get("generated", []) or []:
                if not isinstance(molecule, dict):
                    continue
                child_id = molecule.get("id")
                parent_id = molecule.get("parent_id")
                if child_id and parent_id:
                    relation = (str(parent_id), str(child_id))
                    observed_at = (
                        iteration_number if isinstance(iteration_number, int) else 0
                    )
                    relation_iterations[relation] = min(
                        relation_iterations.get(relation, observed_at), observed_at
                    )
                    parent_sets[str(child_id)].add(str(parent_id))

        for molecule in run.get("molecule_catalog", []) or []:
            remember(molecule)

        roots = tuple(
            dict.fromkeys(
                str(seed["id"])
                for seed in initial_seeds
                if isinstance(seed, dict) and seed.get("id")
            )
        )
        if not roots:
            raise RunGraphError("run has no initial hit molecules")

        graph = nx.DiGraph()
        for molecule_id in molecules:
            layer = min(occurrences[molecule_id] or {0})
            graph.add_node(molecule_id, layer=layer)
        graph.add_edges_from(
            (parent, child)
            for parent, child in sorted(relation_iterations)
            if parent in graph and child in graph
        )
        primary_edges: set[tuple[str, str]] = set()
        discovered = set(roots)
        candidates: list[tuple[int, int, str, str]] = []

        def add_candidates(parent: str) -> None:
            for child in graph.successors(parent):
                heapq.heappush(
                    candidates,
                    (
                        relation_iterations[(parent, child)],
                        graph.nodes[child]["layer"],
                        parent,
                        child,
                    ),
                )

        for root in roots:
            add_candidates(root)
        while candidates:
            _, _, parent, child = heapq.heappop(candidates)
            if child in discovered:
                continue
            discovered.add(child)
            primary_edges.add((parent, child))
            add_candidates(child)
        positions_array = nx.multipartite_layout(
            graph,
            subset_key="layer",
            align="vertical",
            scale=1.0,
        )
        positions = {
            node_id: (float(position[0]), float(position[1]))
            for node_id, position in positions_array.items()
        }
        return cls(
            graph=graph,
            molecules=molecules,
            roots=roots,
            occurrences={
                molecule_id: tuple(sorted(values))
                for molecule_id, values in occurrences.items()
            },
            parents={
                molecule_id: tuple(sorted(values))
                for molecule_id, values in parent_sets.items()
            },
            primary_edges=frozenset(primary_edges),
            positions=positions,
        )

    def edges(self, show_all_edges: bool = False) -> frozenset[tuple[str, str]]:
        return frozenset(self.graph.edges) if show_all_edges else self.primary_edges

    def children(self, molecule_id: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                child
                for child in self.graph.successors(molecule_id)
                if (molecule_id, child) in self.primary_edges
            )
        )

    def visible_nodes(self, expanded: frozenset[str]) -> frozenset[str]:
        visible = set(self.roots)
        changed = True
        while changed:
            changed = False
            for parent_id in tuple(visible & expanded):
                before = len(visible)
                visible.update(self.children(parent_id))
                changed |= len(visible) != before
        return frozenset(visible)

    def visible_edges(
        self,
        visible: frozenset[str],
        expanded: frozenset[str],
        show_all_edges: bool = False,
    ) -> list[tuple[str, str]]:
        visible_relations = {
            (parent, child)
            for parent in sorted(visible & expanded)
            for child in self.children(parent)
            if child in visible
        }
        if show_all_edges:
            visible_relations.update(
                (parent, child)
                for parent, child in self.graph.edges
                if parent in visible and child in visible
            )
        return sorted(visible_relations)

    def node_payload(
        self,
        molecule_id: str,
        expanded: frozenset[str],
    ) -> dict[str, Any]:
        has_children = bool(self.children(molecule_id))
        return {
            "id": molecule_id,
            "dom_id": _dom_token(molecule_id),
            "molecule": self.molecules[molecule_id],
            "iterations": self.occurrences.get(molecule_id, ()),
            "parents": self.parents.get(molecule_id, ()),
            "has_children": has_children,
            "is_leaf": not has_children,
            "expanded": molecule_id in expanded,
            "is_root": molecule_id in self.roots,
        }


def render_svg(
    run_graph: MoleculeRunGraph,
    expanded: frozenset[str],
    show_all_edges: bool = False,
) -> dict[str, Any]:
    visible = run_graph.visible_nodes(expanded)
    edges = run_graph.visible_edges(visible, expanded, show_all_edges)
    available_edges = run_graph.edges(show_all_edges)
    layers = [run_graph.graph.nodes[node_id]["layer"] for node_id in visible]
    layer_counts: defaultdict[int, int] = defaultdict(int)
    for layer in layers:
        layer_counts[layer] += 1
    width = min(18.0, max(7.0, 4.0 + len(set(layers)) * 2.2))
    height = min(13.0, max(4.8, 3.2 + max(layer_counts.values()) * 0.72))

    with (
        _RENDER_LOCK,
        matplotlib.rc_context({"font.family": "DejaVu Sans", "svg.fonttype": "none"}),
    ):
        figure = Figure(figsize=(width, height), facecolor="#ffffff")
        FigureCanvasSVG(figure)
        axes = figure.subplots()
        axes.set_facecolor("#ffffff")

        nx.draw_networkx_edges(
            run_graph.graph,
            run_graph.positions,
            edgelist=edges,
            ax=axes,
            arrows=True,
            arrowstyle="-|>",
            arrowsize=16,
            edge_color="#94a3b8",
            node_size=1_150,
            width=1.35,
            connectionstyle="arc3,rad=0.06",
            min_source_margin=8,
            min_target_margin=12,
        )

        for molecule_id in sorted(visible):
            molecule = run_graph.molecules[molecule_id]
            x, y = run_graph.positions[molecule_id]
            layer = run_graph.graph.nodes[molecule_id]["layer"]
            is_root = molecule_id in run_graph.roots
            is_leaf = not run_graph.children(molecule_id)
            node = axes.scatter(
                [x],
                [y],
                s=680 if is_root else 520,
                marker="s" if is_leaf else ("D" if is_root else "o"),
                c=["#fbbf24" if is_root else _COLORS[max(layer - 1, 0) % len(_COLORS)]],
                edgecolors="#334155",
                linewidths=1.4,
                zorder=3,
            )
            dom_id = _dom_token(molecule_id)
            node.set_gid(f"node-{dom_id}")
            label = axes.annotate(
                _short_label(str(molecule.get("smiles", molecule_id))),
                (x, y),
                xytext=(0, -23 if is_root else -20),
                textcoords="offset points",
                ha="center",
                va="top",
                fontsize=8.3,
                color="#0f172a",
                bbox={
                    "boxstyle": "round,pad=0.24",
                    "facecolor": "#ffffff",
                    "edgecolor": "#e2e8f0",
                    "alpha": 0.96,
                },
                zorder=4,
            )
            label.set_gid(f"label-{dom_id}")

        xs = [run_graph.positions[node_id][0] for node_id in visible]
        ys = [run_graph.positions[node_id][1] for node_id in visible]
        x_span = max(xs) - min(xs)
        y_span = max(ys) - min(ys)
        axes.set_xlim(
            min(xs) - max(0.25, x_span * 0.16),
            max(xs) + max(0.25, x_span * 0.16),
        )
        axes.set_ylim(
            min(ys) - max(0.35, y_span * 0.2),
            max(ys) + max(0.35, y_span * 0.2),
        )
        axes.set_axis_off()
        figure.tight_layout(pad=0.15)

        output = io.StringIO()
        figure.savefig(
            output,
            format="svg",
            transparent=False,
            metadata={"Date": None},
        )
        figure.clear()

    return {
        "svg": output.getvalue(),
        "nodes": [
            run_graph.node_payload(node_id, expanded) for node_id in sorted(visible)
        ],
        "visible_count": len(visible),
        "total_count": run_graph.graph.number_of_nodes(),
        "visible_edge_count": len(edges),
        "total_edge_count": len(available_edges),
        "all_edge_count": run_graph.graph.number_of_edges(),
        "show_all_edges": show_all_edges,
        "fully_expanded": all(
            not run_graph.children(node_id) or node_id in expanded
            for node_id in run_graph.graph.nodes
        ),
    }
