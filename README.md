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
2. **Filter** — Candidates pass through a configurable, ordered chain of filters. Out of the box:
   - **Synthesizability** — reject molecules that would be impractical to synthesize (SAscore / SCscore).
   - **Physicochemical rules** — reject molecules outside drug-like property bounds (Lipinski, Veber).
   - **Docking** — score binding pose/affinity against the target pocket (AutoDock Vina).

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
| `filter-synthesizability` | Scores/gates on synthetic accessibility | Configurable stage |
| `filter-physchem` | Scores/gates on drug-like physicochemical properties | Configurable stage |
| `filter-docking` | Scores/gates on docking pose and binding affinity | Configurable stage |
| `admet-moo` | Scores ADMET properties, ranks via Pareto optimization | Fixed endpoint |
| `orchestrator` | Reads config, sequences service calls, drives the iteration loop | Coordination layer |

Every filter service exposes the same contract, which is what makes them interchangeable:

```
POST /score    { molecules: [...] }  →  { molecules: [...annotated with this stage's fields] }
POST /filter   { molecules: [...] }  →  { passed: [...], rejected: [...] }
```

A shared schema library (`libs/schemas`) defines the `Molecule` object and API models that every service imports, preventing schema drift across service boundaries.

### Configuration-driven pipeline

The order, presence, and thresholds of filter stages are entirely defined in `config/pipeline.yaml` — reordering the pipeline or adding a new filter requires no changes to the orchestrator itself, only a new service definition and a config entry:

```yaml
pipeline:
  - synthesizability:
      threshold: 4.0
  - physchem:
      rules: lipinski
  - docking:
      target_pdb: "6LU7"
      score_threshold: -8.0
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
│   ├── filter-synthesizability/
│   ├── filter-physchem/
│   ├── filter-docking/
│   ├── admet_moo/
│   └── orchestrator/
│       # each service has its own Dockerfile, dependencies, app/, and tests/
├── tests/
│   └── integration/                 # cross-service, full-loop smoke test
├── .github/workflows/               # per-service CI + compose smoke test
└── results/
    └── example_run/                 # committed sample output
```

Unit tests live alongside the service they test; only integration tests that span multiple services live at the repo root.

---

## Running it

```bash
docker compose up
```

This builds and starts every service, then the orchestrator runs the configured pipeline against the example target in `config/targets/`, iterating for the configured number of rounds and writing results to `results/`.

To run against your own target, add a target config with a seed SMILES string, a PDB structure for the binding pocket, and pocket coordinates, then point `pipeline.yaml` at it.

---

## Validation

To demonstrate the pipeline actually works, rather than just "producing output," `results/example_run/` includes a run against a known target where the pipeline is checked against known SAR (structure-activity relationship) trends for that pocket — showing whether the loop recovers previously known potent analogs of the seed molecule and whether the Pareto front improves across iterations.

---

## Status

Portfolio / demonstration project. Not intended for real drug discovery decisions — docking and ADMET predictions here use fast, approximate open-source tools (AutoDock Vina, RDKit-based heuristics) rather than the higher-cost validated methods used in industry pipelines.

### Current implementation

Two fixed-endpoint services are runnable. `generator` accepts one or more hit
SMILES through `POST /generate` and uses REINVENT4 Mol2Mol sampling to generate
structurally related candidates. `admet-moo` accepts filtered candidates through
`POST /optimize`, predicts a modular ADMET objective panel with ADMET-AI, builds
the Pareto front with pymoo, and supports knee-point, desirability/geometric
mean, or hypervolume-contribution lead selection. The filter and orchestrator
services remain planned work. See the service READMEs for API and model details.
