# X-FORGE

**eXtensible Feedback-Optimized Reiterative Generation Engine for Hit-to-Lead Engineering**

> X-FORGE is an independent open-source project and is not affiliated with Cresset's Forge molecular-modeling suite.

X-FORGE is a containerized, config-driven molecular-design loop. It starts from one or more known hits, generates related molecules with REINVENT4 Mol2Mol, evaluates them through modular scientific services, selects multi-objective leads, and feeds those leads into the next iteration while retaining molecule-level provenance.

The current reference workflow is:

```text
seed molecule(s)
      │
      ▼
REINVENT4 Mol2Mol generation
      │
      ▼
synthesizability scoring and gate
      │
      ▼
3D preparation, docking, and binding filters
      │
      ▼
ADMET prediction, Pareto ranking, and lead selection
      │
      └──────── selected leads become the next iteration's seeds
```

The default configuration runs five iterations from Sildenafil against PDE5 structure 1TBF.

## Current services

| Compose service | Role | Host port | Lifecycle |
|---|---|---:|---|
| `generator` | REINVENT4 Mol2Mol candidate generation | `12000` | Resident API |
| `synthesizability` | RA-Score/SAscore composite scoring and filtering | `12002` | Resident API |
| `binding` | RDKit/Meeko preparation, Vina docking, and ProLIF interaction filtering | `12004` | Resident API |
| `admet-moo` | ADMET-AI prediction, Pareto analysis, and lead selection | `12001` | Resident API |
| `orchestrator` | Reads configuration and executes one pipeline run | None | One-shot job |
| `visualizer` | Read-only NetworkX/Matplotlib run explorer | `12010` | Resident web app |

Published ports bind to `127.0.0.1`; services communicate inside Compose by hostname. Port `12003` is intentionally unused so existing port assignments remain stable.

## What each stage does

### Generation

The generator wraps REINVENT4 in Mol2Mol mode. It accepts the current seed set and returns REINVENT-produced candidates with parent identifiers so every generated molecule can be traced back through the run graph.

### Synthesizability

The synthesizability service combines:

- RA-Score, loaded from the official XGBoost model pinned and checksum-verified during the image build.
- RDKit's SAscore, normalized so higher values mean easier synthesis.
- A generalized power mean with `p = -2`, which penalizes a poor component rather than allowing a strong component to hide it.
- A sigmoid activation used as the final thresholdable score.

The service records the raw scores, normalized scores, composite mean, activation, and pass decision.

### Binding

The binding service is deliberately a single ordered service because its operations share prepared structures and poses:

1. RDKit ETKDG conformer generation and MMFF/UFF minimization.
2. Meeko ligand PDBQT preparation.
3. AutoDock Vina docking.
4. Ligand-efficiency and LipE-proxy calculation.
5. ProLIF interaction fingerprinting and critical-interaction checks.

The sample 1TBF protocol uses a prepared chain-A receptor and a docking box centered on the crystallographic Sildenafil site. See [the architecture notes](ARCHITECTURE.md) for its current modeling limitations.

### ADMET multi-objective selection

ADMET-AI currently predicts five modular properties, each represented by an `ADMETProperty` subclass:

- oral bioavailability
- aqueous solubility
- CYP3A4 inhibition
- hERG liability
- drug-induced liver injury (DILI)

PyMOO non-dominated sorting identifies the Pareto front. The configured selection strategy can be knee-point distance, desirability functions with a weighted geometric mean, or hypervolume contribution.

### Orchestration and results

The orchestrator reads `config/services.yaml`, `config/pipeline.yaml`, and the selected target file. It calls service hostnames in configured order, records scores and decisions, selects feedback leads, and writes after every iteration.

Each run directory contains:

```text
results/<run-name>/
├── iteration_001.json
├── iteration_002.json
├── ...
└── run.json
```

Molecule scores are append-only event lists. This preserves repeated observations instead of overwriting an earlier score from another stage or iteration.

### Visualization

The visualizer reads run result JSON without modifying it. Initial hits appear first; clicking a molecule expands or collapses its children, and **Reveal whole graph** exposes all nodes. By default the display uses a single-parent acyclic view; **Show all edges** restores cycles and additional parents. Leaf molecules are square.

## Quick start

Prerequisites:

- Docker with Docker Compose
- the REINVENT Mol2Mol prior at `models/reinvent/mol2mol_medium_similarity.prior`

The prior is mounted into the generator and is intentionally not committed. Target configuration and the prepared 1TBF receptor are included in the repository.

Run the default five-iteration Sildenafil pipeline with an explicit result name:

```bash
XFORGE_RUN_NAME=sildenafil-demo \
  docker compose up --build --abort-on-container-exit \
  --exit-code-from orchestrator orchestrator
```

If `XFORGE_RUN_NAME` is omitted, the orchestrator creates a descriptive directory name from the target slug and a UTC timestamp. Use a unique explicit name: if the directory already exists, files with the same checkpoint names are replaced.

Start the visualizer after the run:

```bash
docker compose up --build -d visualizer
```

Open `http://localhost:12010`, choose a run, and load it. Stop the deployment when finished:

```bash
docker compose down
```

Generator setup and model details are documented in [services/generator/README.md](services/generator/README.md).

## Configuration

Service locations are declared in `config/services.yaml`. Pipeline behavior belongs in `config/pipeline.yaml`, while seed and protein-specific settings belong in `config/targets/*.yaml`.

The current default has this shape (the checked-in file contains the complete binding and HTTP settings):

```yaml
target: targets/sildenafil_pde5.yaml

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

iterations: 5
candidates_per_iteration: 5
top_k_feedback: 2

generator:
  strategy: multinomial
  temperature: 1.0
  random_seed: 42

admet_moo:
  selection:
    method: desirability
    weights:
      herg_blocking: 2.0
```

The full files are the source of truth for timeouts, retry policy, target paths, docking thresholds, property weights, and desirability settings.

## Repository layout

```text
X-FORGE/
├── config/
│   ├── pipeline.yaml             # ordered workflow and loop settings
│   ├── services.yaml             # internal service URLs and timeouts
│   └── targets/                  # seeds and target-specific protocol settings
├── libs/schemas/                 # shared molecule and score-event contracts
├── models/reinvent/              # local, uncommitted REINVENT prior
├── services/
│   ├── generator/
│   ├── synthesizability/
│   ├── binding/
│   ├── admet_moo/
│   ├── orchestrator/
│   └── visualizer/
├── targets/pde5_1tbf/            # prepared receptor and target metadata
├── tests/integration/             # deterministic orchestration tests
├── results/                       # ignored runtime output, except .gitkeep
├── docker-compose.yml
└── ARCHITECTURE.md
```

## Verification status

The repository currently has 58 passing automated tests across the service suites and three top-level orchestration scenarios. Compose configuration and Python linting also pass.

A real five-iteration Compose run completed from Sildenafil against 1TBF. It produced 24 unique candidates, completed every configured stage without recorded errors, and selected two final leads. This validates service integration and provenance handling; it is not evidence that the selected molecules are experimentally active, safe, or synthesizable. The current sample thresholds are intentionally permissive enough to exercise the complete loop.

## Current scope

Implemented now:

- REINVENT4 Mol2Mol generation
- nonlinear RA-Score/SAscore synthesizability filtering
- 3D preparation, Vina docking, efficiency metrics, and interaction filtering
- modular ADMET-AI property prediction and three Pareto selection methods
- configurable iterative orchestration with atomic result persistence
- interactive graph exploration of completed runs
- unit, service, and deterministic integration tests

Not yet implemented includes a separate general physicochemical filter, retrosynthesis planning, experimental calibration, distributed scheduling, authentication, and production deployment controls.

See [ARCHITECTURE.md](ARCHITECTURE.md) for service contracts, provenance design, algorithms, lifecycle decisions, and known limitations.

## License

[MIT](LICENSE)
