# X-FORGE Architecture

This document describes the implemented X-FORGE service boundaries, contracts, data flow, deployment lifecycle, and major design decisions. The top-level [README](README.md) is the operational introduction.

## 1. System overview

X-FORGE is a synchronous feedback pipeline running on a private Docker Compose network. A one-shot orchestrator calls resident scientific APIs in sequence and writes durable checkpoints to a shared results directory.

```text
                                  configuration
                        pipeline.yaml + services.yaml
                                     │
                                     ▼
                            ┌─────────────────┐
                            │  orchestrator   │
                            │ one process/run │
                            └────────┬────────┘
                                     │ HTTP by Compose hostname
                                     ▼
┌───────────┐   ┌──────────────────┐   ┌──────────────────┐   ┌───────────┐
│ generator │──▶│ synthesizability │──▶│     binding      │──▶│ admet-moo │
│ REINVENT4 │   │ RA + SA, p = -2 │   │ prep/Vina/ProLIF │   │ Pareto MOO │
└─────▲─────┘   └──────────────────┘   └──────────────────┘   └─────┬─────┘
      └──────────────── selected feedback molecules ─────────────────┘

              results/<run-name>/*.json
                         │
                         ▼
              ┌────────────────────┐
              │     visualizer     │
              │ read-only web app  │
              └────────────────────┘
```

No service imports another service's implementation. Pipeline envelopes and filter contracts are defined in `libs/schemas` and copied into the images that use them; generator and ADMET-MOO retain service-specific request and response models while preserving the shared molecule fields over HTTP.

### Deployment topology

| Service | Compose hostname | Container/host port | Lifecycle |
|---|---|---:|---|
| Generator | `generator` | `12000` | Resident API |
| ADMET-MOO | `admet-moo` | `12001` | Resident API |
| Synthesizability | `synthesizability` | `12002` | Resident API |
| Binding | `binding` | `12004` | Resident API |
| Orchestrator | `orchestrator` | None | One-shot job |
| Visualizer | `visualizer` | `12010` | Resident read-only UI |

Host ports bind only to `127.0.0.1`; internal calls use the Compose DNS names in `services.yaml`. Port `12003` is unassigned. The visualizer is intentionally absent from the scientific service registry.

Compose waits for the four scientific APIs to report healthy before launching the orchestrator. Generator health verifies the prior and REINVENT runtime, ADMET health loads its predictor, and synthesizability health loads the real RA-Score artifact. Binding health currently verifies its installed scientific stack; target paths are validated when a scoring request creates a docking context.

The sample Compose manifest declares all four APIs as orchestrator dependencies. Pipeline configuration controls which filter APIs are called, although an unused declared filter container may still start.

## 2. Configuration model

Configuration separates experimental intent from deployment location:

- `config/pipeline.yaml` defines the target, filter order and parameters, iteration budget, generator options, ADMET decision policy, and HTTP retry behavior.
- `config/services.yaml` maps logical service names to network URLs.
- `config/targets/*.yaml` defines a target name and one or more starting molecules.
- `targets/<target-id>/` contains prepared receptor and docking-box assets mounted read-only into the binding container.

The current pipeline shape is:

```yaml
target: targets/sildenafil_pde5.yaml

pipeline:
  - synthesizability:
      power: -2
      rascore_weight: 1.0
      sascore_weight: 1.0
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

admet_moo:
  properties: null
  selection:
    method: desirability
    weights:
      herg_blocking: 2.0
```

At orchestrator startup, Pydantic validates both YAML files, resolves the target relative to `config/`, verifies that every configured stage has a service URL, and rejects malformed stage or run names. An empty `pipeline: []` is valid and connects generation directly to ADMET-MOO.

## 3. HTTP contracts

### Filter contract

Synthesizability and binding expose the same two-stage interface:

```text
POST /score
  request:  {molecules: [Molecule, ...], parameters: {...}}
  response: {molecules: [Molecule with one appended ScoreRecord, ...]}

POST /filter
  request:  {molecules: [scored Molecule, ...], parameters: {...}}
  response: {passed: [...], rejected: [...]}
```

`/score` calculates and annotates; `/filter` only partitions. The latter requires the molecule's latest score record to belong to that service, preventing stale or unscored data from being gated. Keeping the operations separate lets a score be retained before the molecule is removed from the active population and lets thresholds be re-examined without conflating calculation with orchestration.

### Generator contract

```text
POST /generate
  request:
    seeds, n_candidates_per_seed, strategy, temperature, random_seed
  response:
    molecules, requested, generated, model
```

Each generated item includes its REINVENT-produced SMILES, stable ID, immediate parent SMILES/ID, Tanimoto similarity, and REINVENT negative log-likelihood when available.

### ADMET-MOO contract

```text
GET  /properties
POST /optimize
  request:
    molecules, top_k, optional property keys, selection options
  response:
    all evaluated molecules, selected molecules, Pareto front,
    selected method, and property metadata
```

Evaluated molecules contain raw predictions, minimization-form objectives, unit desirabilities, Pareto rank, selection score, and selected state. The service appends one `admet_moo` score record without deleting existing filter history.

Scientific APIs expose `GET /live` for process liveness and `GET /health` for readiness. The visualizer exposes `GET /health` plus read-only run and graph APIs.

## 4. Molecule and provenance model

The core schema is:

```python
class ScoreRecord(BaseModel):
    stage: str
    values: dict[str, float]
    passed: bool | None
    computed_at_iteration: int

class Molecule(BaseModel):
    smiles: str
    id: str | None
    parent_id: str | None
    iteration: int
    scores: list[ScoreRecord]
```

The envelope permits extra service-specific metadata such as generator model details, binding interactions, synthesizability diagnostics, ADMET objectives, and selection state.

IDs are the first 16 hexadecimal characters of SHA-256 over the stored SMILES. The shared schema only trims and validates a supplied one-line SMILES; it does not canonicalize it. REINVENT canonicalizes input representations during sampling, but X-FORGE hashes the exact candidate representation returned in REINVENT's output, so callers and future generators are responsible for consistent SMILES normalization.

Each generated snapshot stores its immediate `parent_id`. Repeated generation of the same molecular ID can produce extra parent edges across iteration artifacts; the top-level ledger keeps the latest append-only snapshot, while iteration checkpoints retain the historical occurrences needed to reconstruct the fuller graph.

Score history is append-only because a mutable dictionary keyed by stage would discard repeated observations. The orchestrator enforces this invariant and also rejects service responses that:

- change the population during `/score`
- return an incomplete or overlapping filter partition
- reorder or rewrite the existing score prefix
- return duplicate generated IDs or an unknown parent ID

## 5. Scientific services

### 5.1 Generator

The generator wraps REINVENT4 v4.8 Mol2Mol sampling. The model prior is mounted at runtime from `models/reinvent/mol2mol_medium_similarity.prior`, allowing the large artifact to remain outside version control. Requests support multinomial or beam-search sampling, temperature, and a deterministic random seed.

The orchestrator treats `candidates_per_iteration` as a total budget. Because the generator samples per seed, it divides that budget across the current seeds, rounds up, and trims excess candidates. REINVENT is configured to request unique output, and the orchestrator rejects duplicate returned IDs. It converts returned Tanimoto/NLL values into an append-only `generator` score record.

### 5.2 Synthesizability

For each valid RDKit molecule, the service calculates:

- RA-Score from a pinned, checksum-verified upstream XGBoost artifact using count-based ECFP6 input.
- RDKit SAscore.

The values are converted to positive desirabilities:

```text
r = clamp(RA-Score, epsilon, 1)
s = clamp((SA_worst - SAscore) / (SA_worst - SA_best), epsilon, 1)
```

They are combined using the configured positive weights and fixed power `p = -2`:

```text
M = ((w_ra * r^-2 + w_sa * s^-2) / (w_ra + w_sa))^(-1/2)
activation = sigmoid(steepness * (M - midpoint))
passed = activation >= min_activation
```

The negative power limits compensation by the stronger input. Raw metrics, normalized inputs, power mean, activation, success flag, and per-molecule errors are retained. A bad molecule is rejected without failing the whole batch.

### 5.3 Binding

Binding is one composite service because each operation depends on the structure or pose created by the previous operation:

1. Parse SMILES, add hydrogens, generate an ETKDGv3 conformer, and minimize with MMFF or UFF.
2. Prepare ligand PDBQT with Meeko.
3. Dock with AutoDock Vina.
4. Reconstruct returned poses and fingerprint protein-ligand contacts with ProLIF.
5. Calculate Vina score, ligand efficiency, a Vina-derived pKd proxy, LipE proxy, interaction coverage, and geometric binding desirability.
6. Apply configured affinity, efficiency, LipE, and critical-interaction gates.

Receptors and Vina maps are cached by target configuration. Access to each Vina context is locked because a Vina instance holds mutable ligand state. Preparation or docking failure rejects only the affected molecule; invalid target configuration fails the request.

The current PDE5 protocol is documented alongside its assets in [targets/pde5_1tbf/README.md](targets/pde5_1tbf/README.md).

### 5.4 ADMET-MOO

ADMET-AI performs one batch prediction. Five registered `ADMETProperty` subclasses translate its output into objective and desirability values:

| Property key | Goal |
|---|---|
| `bioavailability` | Maximize |
| `aqueous_solubility` | Maximize |
| `cyp3a4_inhibition` | Minimize |
| `herg_blocking` | Minimize |
| `dili` | Minimize |

New objectives are added by implementing the `ADMETProperty` interface and registering the class. The request may choose a subset of active properties.

PyMOO `NonDominatedSorting` assigns ranks; this service is not running an NSGA-II evolutionary search. Only rank-zero molecules are considered by the requested final decision method:

- `knee_point`: PyMOO high-tradeoff points with deterministic distance-to-ideal fallback.
- `desirability`: optionally weighted geometric mean of endpoint desirabilities.
- `hypervolume_contribution`: unique normalized-front hypervolume contribution against a validated reference point.

## 6. Orchestration lifecycle

The orchestrator is a batch job, not a server. One container invocation:

1. Loads and validates configuration.
2. Creates `results/<run-name>/run.json` with status `running`.
3. Waits for required services with configured retries and backoff.
4. Generates the per-iteration candidate budget.
5. Calls `/score` then `/filter` for each configured stage.
6. Sends survivors to ADMET-MOO and chooses at most `top_k_feedback` Pareto-front molecules.
7. Writes an iteration checkpoint and refreshes `run.json`.
8. Feeds selected molecules into the next iteration.
9. Marks the run `completed` or `failed` and exits.

Normal early termination occurs when generation returns no candidates, all candidates are filtered, or ADMET-MOO selects no leads. There is currently no convergence or Pareto-improvement stopping rule.

Each iteration artifact records input seeds, generated candidates, every filter's passed and rejected populations, survivors, all ADMET-evaluated molecules, the Pareto front, and selected feedback leads. `run.json` adds timestamps, status, termination reason, all iteration summaries, final selection, and a deduplicated molecule catalog.

Writes use a temporary file followed by an atomic rename. A user-provided `XFORGE_RUN_NAME` selects the result subdirectory; otherwise the name is derived from the target slug and a high-resolution UTC timestamp. Explicit names should be unique: a pre-existing directory is reused and same-named checkpoint files are replaced.

## 7. Visualization architecture

The visualizer mounts `results/` read-only and never participates in orchestration. Its backend validates run names, loads result JSON, builds lineage with NetworkX, computes layout, and renders graph layers as Matplotlib SVG. The browser handles visibility and interaction:

- only initial hits are visible at load
- clicking a node reveals or hides its descendant branch
- **Reveal whole graph** exposes all nodes
- the default single-parent acyclic edge set suppresses cycles and additional parents
- **Show all edges** restores every observed edge
- leaf nodes are square
- hover metadata is derived from the run artifact

This split keeps chemistry/provenance parsing server-side while leaving graph exploration responsive and prevents result mutation through the UI.

## 8. Models and reproducibility

| Artifact | Handling |
|---|---|
| REINVENT Mol2Mol prior | Supplied locally, ignored by Git, mounted read-only |
| REINVENT4 source/runtime | Built from the versioned Compose build argument (`v4.8`) |
| RA-Score model | Downloaded from a pinned commit and checksum-verified at image build |
| ADMET-AI model | Loaded by the ADMET-AI package during service readiness |
| 1TBF receptor assets | Versioned under `targets/pde5_1tbf/`, mounted read-only |

Random seeds are configurable for REINVENT and Vina. RDKit conformer generation derives a stable seed from molecular SMILES. Exact numerical reproduction can still depend on container image, model, CPU/library implementation, and upstream prediction behavior.

## 9. Verification

The current repository has 58 passing tests:

- generator: 11
- synthesizability: 6
- binding: 4
- ADMET-MOO: 18
- orchestrator: 10
- visualizer: 6
- top-level integration: 3

The top-level tests exercise deterministic fake-service loops, including the current five-iteration stage order. A separate real Compose run from Sildenafil against 1TBF completed all five iterations with 24 unique generated candidates, no recorded stage errors, and two final selected leads. That run verifies deployment and contract integration, not prospective scientific validity.

## 10. Architecture decisions

### Synchronous REST instead of a queue

Current runs contain small populations on one Compose host. REST is inspectable, directly testable, and sufficient for the sequential data dependency. A queue and distributed workers would become useful if docking throughput or horizontal scaling became a requirement.

### Configured filters, fixed generator and selector

Generator and ADMET-MOO are the feedback loop's required endpoints. Intermediate filters use a common contract and ordered configuration. The internal binding operations remain fixed because exposing pose-dependent steps as freely reorderable services would create invalid combinations and move large transient pose artifacts through the shared envelope.

### Append-only molecule events

Provenance is part of the persisted data model rather than only application logs. Services append observations, and the orchestrator verifies previous history before accepting a response.

### One-shot orchestrator

A run has a clear beginning, durable checkpoints, terminal status, and process exit code. Keeping the coordinator as a batch job avoids an idle API container and makes Compose suitable for launching and observing a single experiment.

### NetworkX/Matplotlib visualizer

The server owns lineage normalization and deterministic SVG rendering; browser JavaScript owns expansion state and metadata interaction. A separate read-only service keeps result inspection independent of scientific execution.

## 11. Known limitations

- The system is a portfolio and integration platform, not a validated drug-discovery decision system.
- The current 1TBF receptor removes catalytic zinc, magnesium, ordered waters, glycerol, and the crystallographic ligand. This makes a deterministic demonstration target, not a validated PDE5 docking protocol.
- Binding uses a rigid receptor and retains scores/interactions in JSON, not reusable docked pose files.
- The LipE value is a Vina-derived proxy, not an experimentally measured potency-based LipE.
- RA-Score has the applicability domain and labeling assumptions of its upstream training data; it is not a retrosynthesis plan.
- ADMET-AI predictions and desirability curves have not been calibrated for a specific discovery program.
- Current default thresholds are permissive to exercise the complete loop.
- Each service is single-container and CPU-oriented; binding serializes access to a target's Vina context.
- There is no authentication, authorization, job queue, distributed scheduler, or automatic resume of interrupted runs.
- Service URLs and localhost ports are suitable for a trusted local deployment, not direct public exposure.
