# X-FORGE

**eXtensible Feedback-Optimized Reiterative Generation Engine for Hit-to-Lead Engineering**

> Not to be confused with Cresset's "Forge" molecular modeling suite — X-FORGE is an independent, open-source project.

X-FORGE is a modular, closed-loop pipeline for computational hit-to-lead optimization. Starting from a single known "hit" molecule (a SMILES string with confirmed binding activity against a target pocket), it iteratively generates, filters, and scores structurally related candidates — using multi-objective optimization over ADMET properties to select the most promising molecules to seed the next round of generation.

Each stage of the pipeline is an independently deployable service, orchestrated via Docker Compose. Filter stages (synthesizability, physicochemical rules, docking, or anything you add) can be reordered, swapped, or removed entirely through configuration — no code changes required.

---

## What it does

Drug discovery's hit-to-lead phase is fundamentally iterative: take a molecule known to bind a target, generate variations on it, throw out the bad ones, and repeat until you converge on candidates worth synthesizing and testing. X-FORGE automates that loop end-to-end:

```
                    ┌─────────────────────────────────────────────┐
                    │                                               │
                    ▼                                               │
   seed SMILES ──▶ [Generator] ──▶ [Filter chain] ──▶ [ADMET + MOO] │
                                    (configurable,                   │
                                     reorderable,                    │
                                     extensible)                     │
                                          │                          │
                                          └── top-K candidates ──────┘
                                              (next iteration seed)
```

1. **Generate** — A generative model (e.g., genetic-algorithm mutation over SELFIES, or a fine-tuned RL model like REINVENT4) proposes structurally similar candidate molecules from the current seed set.
2. **Filter** — Candidates pass through a configurable, ordered chain of
   filters. The implemented **synthesizability** filter combines RA-Score and
   SAscore with a sigmoid-gated `p = -2` generalized power mean before the
   **binding** filter prepares 3D ligands, docks them with AutoDock Vina,
   calculates efficiency metrics, and checks pose interactions with ProLIF.
   Additional physicochemical filters remain planned extensions.

   Filters can be added, removed, or reordered via config — none of them need to know what ran before or after them.
3. **ADMET + Multi-Objective Optimization** — Surviving candidates are scored across ADMET properties (absorption, distribution, metabolism, excretion, toxicity) and ranked using Pareto-based multi-objective optimization (non-dominated sorting), since these objectives routinely trade off against each other.
4. **Feedback** — The top candidates from the Pareto front become the seed set for the next generation round. Repeat for *n* iterations.

The generative model and the ADMET/MOO step are fixed endpoints of the pipeline. Everything in between is swappable.

---

## Why this design

This project is built to demonstrate production engineering practices applied to a real, multi-stage scientific ML workflow — not to claim novelty in the underlying chemistry methods (SAscore, Vina, ADMET prediction, and NSGA-II-style Pareto ranking are all established, off-the-shelf techniques). The goal is a pipeline that is:

- **Modular** — each stage is a separate service with a uniform REST contract, so filters are additive rather than invasive.
- **Reproducible** — a single `docker compose up` on a clean machine reproduces a full run from scratch, with all dependencies pinned.
- **Observable** — every molecule carries a full record of scores and provenance as it flows through the pipeline, so you can audit exactly why a candidate survived or was rejected at any stage.
- **Tested at every level** — per-service unit tests, a shared-schema test suite, and a cross-service integration smoke test that runs the full loop on a toy example in CI.

---

## Architecture

X-FORGE is a set of independently containerized services on a shared Docker Compose network, coordinated by an orchestrator that reads pipeline configuration and calls each service by hostname.

| Service | Role | Fixed or configurable |
|---|---|---|
| `generator` | Proposes candidate molecules from seed SMILES | Fixed endpoint |
| `synthesizability` | RA-Score + SAscore sigmoid-gated `p = -2` synthetic-accessibility filter | Configurable stage |
| `filter-physchem` | Scores/gates on drug-like physicochemical properties | Configurable stage |
| `binding` | RDKit/Meeko preparation, Vina docking, efficiency metrics, and ProLIF pose gates | Configurable stage |
| `admet-moo` | Scores ADMET properties, ranks via Pareto optimization | Fixed endpoint |
| `orchestrator` | Reads config, sequences service calls, drives the iteration loop | Coordination layer |
| `visualizer` | Interactively explores molecule lineage and score history | Read-only UI |

Every filter service exposes the same contract, which is what makes them interchangeable:

```
POST /score    { molecules: [...], parameters: {...} }  →  { molecules: [...annotated] }
POST /filter   { molecules: [...], parameters: {...} }  →  { passed: [...], rejected: [...] }
```

A shared schema library (`libs/schemas`) defines the `Molecule` object and API models that every service imports, preventing schema drift across service boundaries.

### Configuration-driven pipeline

The order, presence, and thresholds of filter stages are entirely defined in `config/pipeline.yaml` — reordering the pipeline or adding a new filter requires no changes to the orchestrator itself, only a new service definition and a config entry:

```yaml
pipeline:
  - synthesizability:
      power: -2
      gate_midpoint: 0.5
      gate_steepness: 12.0
      min_activation: 0.5
  - binding:
      receptor_pdbqt: /targets/pde5_1tbf/1tbf_chain_a_receptor.pdbqt
      receptor_pdb: /targets/pde5_1tbf/1tbf_chain_a_prepared.pdb
      box_center: [28.792, 30.186, 64.179]
      box_size: [24.0, 24.0, 24.0]
      max_vina_score: -4.0
```

A separate `config/services.yaml` maps each named stage to its network location, keeping "what runs, in what order, with what thresholds" cleanly separate from "where does each stage actually live" — a seam that also means the same pipeline config could target a different deployment (e.g., Kubernetes) by swapping only the service registry.

---

## Repository layout

```
x-forge/
├── docker-compose.yml
├── docker-compose.override.yml     # dev-only overrides
├── config/
│   ├── pipeline.yaml                # filter order + thresholds
│   ├── services.yaml                # stage name → hostname mapping
│   └── targets/                     # seed SMILES, target PDB, pocket definitions
├── libs/
│   └── schemas/                     # shared Molecule / API models
├── services/
│   ├── generator/
│   ├── synthesizability/
│   ├── filter-physchem/
│   ├── binding/
│   ├── admet_moo/
│   ├── orchestrator/
│   └── visualizer/
│       # each service has its own Dockerfile, dependencies, app/, and tests/
├── tests/
│   └── integration/                 # cross-service, full-loop smoke test
├── .github/workflows/               # per-service CI + compose smoke test
└── results/
    └── <run-name>/                  # iteration checkpoints + full run output
```

Unit tests live alongside the service they test; only integration tests that span multiple services live at the repo root.

---

## Running it

```bash
XFORGE_RUN_NAME=my-sildenafil-run \
docker compose up --build \
  --abort-on-container-exit \
  --exit-code-from orchestrator \
  orchestrator
```

This builds and starts every service, then the orchestrator runs the configured pipeline against the example target in `config/targets/`, iterating for the configured number of rounds and writing results to `results/`.

`XFORGE_RUN_NAME` selects the subdirectory beneath `results/`. It may contain
letters, numbers, dots, underscores, and hyphens. Omit it to automatically use
the target name and UTC start time, such as
`results/sildenafil-pde5-1tbf-20260830T194631123456Z/`.

To run against your own target, add a target config with a seed SMILES string, a PDB structure for the binding pocket, and pocket coordinates, then point `pipeline.yaml` at it.

### Visualizing a run

Start the persistent, read-only results viewer separately:

```bash
docker compose up --build -d visualizer
```

Open <http://localhost:12010>. Choose a run, click a molecule to reveal or hide
its children, and hover over any node to inspect provenance and score metadata.
Only the initial hits are shown initially; **Reveal whole graph** expands every
lineage branch at once. The default view suppresses cycles and repeated-parent
edges; select **Show all edges** to include them.

---

## Validation

To demonstrate the pipeline actually works, rather than just "producing output," a named run directory can be retained and checked against known SAR (structure-activity relationship) trends for its target pocket — showing whether the loop recovers previously known potent analogs of the seed molecule and whether the Pareto front improves across iterations.

---

## Status

Portfolio / demonstration project. Not intended for real drug discovery decisions — docking and ADMET predictions here use fast, approximate open-source tools (AutoDock Vina, RDKit-based heuristics) rather than the higher-cost validated methods used in industry pipelines.

### Current implementation

The two fixed-endpoint services, synthesizability and binding filters,
orchestration loop, and run visualizer are runnable.
`generator` accepts one or more hit
SMILES through `POST /generate` and uses REINVENT4 Mol2Mol sampling to generate
structurally related candidates. `admet-moo` accepts filtered candidates through
`POST /optimize`, predicts a modular ADMET objective panel with ADMET-AI, builds
the Pareto front with pymoo, and supports knee-point, desirability/geometric
mean, or hypervolume-contribution lead selection. `orchestrator` reads the YAML
configuration, drives the iterative feedback loop, and writes auditable run and
per-iteration results. `binding` performs RDKit/Meeko 3D preparation, Vina
docking, ligand-efficiency and LipE-proxy calculation, and ProLIF interaction
fingerprinting. `synthesizability` preserves raw RA-Score and SAscore values,
their unit desirabilities, the `p = -2` power mean, and the final sigmoid
activation in every molecule's audit history. The checked-in example runs five
feedback iterations from sildenafil against the prepared 1TBF PDE5A target in
the order generation → synthesizability → binding → ADMET/MOO.
See the service READMEs for API and runtime details.
