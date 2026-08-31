from __future__ import annotations

from app.run_graph import MoleculeRunGraph, render_svg


def _cyclic_run() -> dict:
    return {
        "initial_seeds": [{"id": "hit", "smiles": "CCO", "iteration": 0, "scores": []}],
        "iterations": [
            {
                "iteration": 1,
                "generated": [
                    {
                        "id": "candidate",
                        "parent_id": "hit",
                        "smiles": "CCN",
                        "iteration": 1,
                        "scores": [],
                    }
                ],
            },
            {
                "iteration": 2,
                "generated": [
                    {
                        "id": "lead",
                        "parent_id": "candidate",
                        "smiles": "CCC",
                        "iteration": 2,
                        "scores": [],
                    }
                ],
            },
            {
                "iteration": 3,
                "generated": [
                    {
                        "id": "candidate",
                        "parent_id": "lead",
                        "smiles": "CCN",
                        "iteration": 3,
                        "scores": [{"stage": "generator"}],
                    }
                ],
            },
        ],
        "molecule_catalog": [
            {
                "id": "candidate",
                "parent_id": "lead",
                "smiles": "CCN",
                "iteration": 3,
                "scores": [{"stage": "generator"}],
            }
        ],
    }


def test_networkx_model_preserves_cycles_and_progressive_visibility() -> None:
    run_graph = MoleculeRunGraph.from_run(_cyclic_run())

    assert run_graph.roots == ("hit",)
    assert set(run_graph.graph.edges) == {
        ("hit", "candidate"),
        ("candidate", "lead"),
        ("lead", "candidate"),
    }
    assert run_graph.primary_edges == {
        ("hit", "candidate"),
        ("candidate", "lead"),
    }
    assert run_graph.occurrences["candidate"] == (1, 3)
    assert run_graph.visible_nodes(frozenset()) == {"hit"}
    assert run_graph.visible_nodes(frozenset({"hit"})) == {"hit", "candidate"}
    assert run_graph.visible_nodes(frozenset({"hit", "candidate"})) == {
        "hit",
        "candidate",
        "lead",
    }
    assert run_graph.visible_nodes(frozenset({"hit"})) == {"hit", "candidate"}
    assert run_graph.visible_nodes(frozenset()) == {"hit"}


def test_matplotlib_svg_contains_only_visible_node_artists() -> None:
    run_graph = MoleculeRunGraph.from_run(_cyclic_run())

    initial = render_svg(run_graph, frozenset())
    expanded = render_svg(run_graph, frozenset({"hit"}))
    complete = render_svg(run_graph, run_graph.node_ids)
    complete_with_all_edges = render_svg(
        run_graph,
        run_graph.node_ids,
        show_all_edges=True,
    )

    assert initial["visible_count"] == 1
    assert initial["total_count"] == 3
    assert 'id="node-mol-aGl0"' in initial["svg"]
    assert 'id="node-mol-Y2FuZGlkYXRl"' not in initial["svg"]
    assert 'id="node-mol-Y2FuZGlkYXRl"' in expanded["svg"]
    assert initial["fully_expanded"] is False
    assert complete["visible_count"] == 3
    assert complete["visible_edge_count"] == complete["total_edge_count"] == 2
    assert complete["all_edge_count"] == 3
    assert complete["fully_expanded"] is True
    assert complete["show_all_edges"] is False
    assert complete_with_all_edges["visible_edge_count"] == 3
    assert complete_with_all_edges["total_edge_count"] == 3
    assert complete_with_all_edges["show_all_edges"] is True
    assert run_graph.node_payload("lead", frozenset())["is_leaf"] is True
    assert run_graph.node_payload("candidate", frozenset())["is_leaf"] is False
