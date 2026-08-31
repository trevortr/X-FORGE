# X-FORGE Architecture

This document describes how X-FORGE is put together: the service boundaries, the data model that flows between them, the network topology, and the reasoning behind the major design decisions. The README describes *what* X-FORGE does; this document describes *how* and *why*.

---

## 1. System overview

X-FORGE is a set of independently deployable services on a shared Docker Compose network, coordinated by a single orchestrator. There are two **fixed endpoints** of the pipeline — the generator and the ADMET/multi-objective optimization (MOO) step — and an arbitrary, config-defined chain of **filter stages** in between.

```
                         ┌────────────────────────────────────────────┐
                         │              orchestrator                   │
                         │  reads config/pipeline.yaml                 │
                         │  reads config/services.yaml                 │
                         │  drives the n-iteration loop                │
                         └───────┬──────────────────────────┬─────────┘
                                 │                            │
                    calls services by hostname, in configured order
                                 │                            │
        ┌────────────────────────────────────────────────────────────────┐
        │                                                                  │
        ▼                                                                  ▼
  ┌───────────┐       ┌───────────────────────────┐       ┌───────────┐
  │ generator │──────▶│ binding                   │──────▶│ admet-moo │
  │ (fixed)   │       │ RDKit → Meeko → Vina      │       │ (fixed)   │
  └───────────┘       │ → efficiency → ProLIF     │       └─────┬─────┘
        ▲             └───────────────────────────┘             │
        │                                                       │
        └────────── top-K Pareto-selected candidates ───────────┘
                                    (next iteration's seed set)
```

Each box is its own container, its own codebase, its own test suite, and its own Dockerfile. None of them import each other's code — the only thing they share is a schema library (`libs/schemas`) and an HTTP contract.

The `visualizer` is outside the scientific pipeline call chain. It is a
persistent read-only web service on port 12010 that mounts `results/`, lists run
artifacts, builds lineage graphs with NetworkX, and renders them as interactive
Matplotlib SVG. Keeping it out
of `config/services.yaml` prevents a presentation concern from becoming a
pipeline stage. Port 12004 is assigned to the binding filter; ports 12002 and
12003 remain available for synthesizability and other future filters.

---

## 2. Service contract

Every filter service — regardless of what it actually computes — exposes the same two endpoints:

```
POST /score
  request:  { "molecules": [Molecule, ...], "parameters": {...} }
  response: { "molecules": [Molecule, ...] }   # same molecules, annotated with this stage's fields

POST /filter
  request:  { "molecules": [Molecule, ...], "parameters": {...} }
  response: { "passed": [Molecule, ...], "rejected": [Molecule, ...] }

GET /health
  response: { "status": "ok" }
```

`generator` and `admet-moo` deviate slightly since they aren't gating stages:

```
POST /generate
  request:  { "seeds": [Molecule, ...], "n_candidates_per_seed": int }
  response: { "molecules": [Molecule, ...] }

POST /optimize
  request:  { "molecules": [Molecule, ...], "top_k": int }
  response: { "selected": [Molecule, ...], "pareto_front": [Molecule, ...] }
```

**Why separate `/score` from `/filter`** rather than one endpoint that scores-and-gates: you often want a stage's score computed and recorded even for molecules that will be rejected by an earlier stage's threshold, or for post-hoc analysis of where thresholds should be set. Keeping them separate means the orchestrator decides when to gate, and every score is preserved in the molecule's record regardless of pass/fail — nothing is silently discarded.

**Why this uniformity matters**: it's what makes a filter genuinely swappable at the network level. The orchestrator's HTTP client doesn't have per-filter-type logic — it calls `/score` and `/filter` on whatever hostname the config points it to. Adding a new filter type means writing a new service that honors this contract and adding one line to `services.yaml`; the orchestrator's code does not change.

---

## 3. The `Molecule` object

Defined once in `libs/schemas`, imported by every service. This is the single most important shared artifact in the system — schema drift here would silently break the pipeline.

```python
class ScoreRecord(BaseModel):
    stage: str                      # e.g. "docking", "physchem"
    values: dict[str, float]        # e.g. {"binding_affinity": -8.4}
    passed: bool | None             # None if this stage only scores, doesn't gate
    computed_at_iteration: int

class Molecule(BaseModel):
    smiles: str
    id: str                         # stable hash of canonical SMILES
    parent_id: str | None           # provenance: which molecule it was derived from
    iteration: int                  # which loop iteration produced it
    scores: list[ScoreRecord]       # full history, append-only across the pipeline
```

**Why molecules carry their full score history, not just current-stage output**: since the filter chain is reorderable and extensible, no stage can assume what ran before it beyond what it explicitly declares as a dependency (see §5). Carrying the full history also means the entire run is auditable after the fact — you can answer "which stage kills the most candidates" or "did iteration 3's survivors actually improve on iteration 1's Pareto front" without rerunning anything, since every score from every stage of every iteration is preserved on the molecule record itself.

**Why an append-only list rather than a mutable dict keyed by stage name**: if a filter runs more than once across iterations (which it will, every loop iteration), a dict would overwrite prior iterations' scores. The list plus `computed_at_iteration` preserves the full trajectory of each molecule's scores across the entire run — useful for the validation analysis described in the README (checking that the Pareto front actually improves iteration over iteration).

---

## 4. Configuration

Two config files, deliberately kept separate:

**`config/pipeline.yaml`** — what runs, in what order, with what thresholds:
```yaml
pipeline:
  - binding:
      receptor_pdbqt: /targets/cox2_4ph9/4ph9_chain_a_receptor.pdbqt
      receptor_pdb: /targets/cox2_4ph9/4ph9_chain_a_prepared.pdb
      box_center: [13.008, 23.487, 25.256]
      box_size: [22.0, 22.0, 22.0]
      max_vina_score: -4.0
iterations: 4
candidates_per_iteration: 5
top_k_feedback: 2
```

**`config/services.yaml`** — where each named stage actually lives:
```yaml
services:
  generator:        "http://generator:12000"
  admet_moo:        "http://admet-moo:12001"
  binding:          "http://binding:12004"
```

**Why two files instead of one**: `pipeline.yaml` answers a scientific/experimental question (what filters, what order, what thresholds) and is what you'd change between experiments. `services.yaml` answers a deployment question (what network location serves this stage) and is what you'd change between environments (local Compose vs. a future Kubernetes deployment). Conflating them would mean every environment change requires touching experiment config, and vice versa.

---

## 5. Pipeline construction and stage dependencies

The orchestrator's `ConfigurationLoader` reads `pipeline.yaml`, resolves each named stage against `services.yaml`, and constructs an ordered call sequence — failing fast at build time (not mid-run) if a stage is referenced in one file but missing from the other.

The binding operation has an internal dependency chain: RDKit 3D preparation,
Meeko parameterization, Vina docking, efficiency calculation, then ProLIF pose
analysis. These are deliberately one composite filter because exposing them as
independently reorderable services would create invalid pipeline arrangements
and force large pose artifacts through the shared molecule contract. The
binding service retains each component metric in one auditable score record.

An empty `pipeline: []` is a valid configuration — generation feeds directly into ADMET/MOO. This is the minimal-viable-loop mode and is exercised directly by the integration smoke test, since it's the cheapest possible full run of the system.

---

## 6. The feedback loop

Each iteration:

1. `generator` produces `candidates_per_iteration` molecules from the current seed set.
2. Candidates flow through the configured filter chain; each stage scores and gates.
3. Survivors are sent to `admet-moo`, which predicts ADMET properties with ADMET-AI and performs non-dominated (Pareto) sorting with pymoo.
4. The human-selected decision method — knee point, desirability functions with weighted geometric mean, or hypervolume contribution — ranks only the Pareto-front molecules. The top `top_k_feedback` become the next iteration's seed set.
5. Repeat for the configured number of iterations, or until a stopping criterion is met (e.g., Pareto front stops improving).

The population setting is a total per-iteration budget even though the
generator API samples per seed. The orchestrator divides the budget across the
current seed set, rounds up, and trims any excess returned candidates. It also
adds a `generator` score record containing REINVENT's Tanimoto/NLL values before
the molecules enter the filter chain.

### Run artifacts and lineage

The orchestrator retains more than the final leads. Every iteration checkpoint
contains its input seeds, all generated candidates, passed and rejected
populations from each filter, all ADMET-evaluated survivors, the Pareto front,
and selected feedback molecules. A top-level `run.json` combines those
checkpoints with run status/timestamps and a deduplicated molecule catalog.
Each invocation writes these files beneath `results/<run-name>/`. The run name
is supplied at launch or defaults to a filesystem-safe combination of the
target name and a high-resolution UTC timestamp, so independent runs do not
silently share one output directory.

For a molecule ID seen again in a later iteration, the orchestrator starts from
its latest known score history and appends new records. It rejects any service
response that changes the input population during scoring, returns an invalid
filter partition, or rewrites the existing score prefix. Children keep only
their immediate `parent_id`; the complete ancestry remains reconstructable by
following IDs through the molecule catalog.

**Why Pareto selection rather than a single scalarized reward**: ADMET objectives routinely trade off against each other (e.g., improving metabolic stability can worsen solubility), and collapsing them into one weighted score requires committing to relative weights up front, which is exactly the kind of judgment call that's better made by inspecting a front than baked into a formula. Non-dominated sorting (NSGA-II-style) surfaces the actual trade-off surface instead of a single number.

**Why make Pareto-front decision-making configurable**: the front separates objective trade-offs from the human preference used to pick leads. Knee-point selection favors high-tradeoff compromises, desirability functions encode explicit endpoint preferences, and hypervolume contribution favors candidates that preserve the largest unique portion of objective space. This lets an experiment change its decision policy without changing prediction or Pareto-ranking code.

---

## 7. Architecture Decision Records

### ADR-1: REST over a message queue for inter-service communication
**Decision**: Services communicate via synchronous HTTP/REST, not an async queue (Celery/RabbitMQ/etc.).
**Reasoning**: At this system's scale (tens to low-hundreds of molecules per iteration, single-machine Compose deployment), the queue's benefits — decoupled producers/consumers, backpressure handling, horizontal fan-out — aren't load-bearing, but its costs (broker to run and monitor, harder to debug, harder to demo) are real. REST is directly curl-able during development and easy to represent in a single sequence diagram. A queue-based design is documented here as a natural extension point if the project were scaled to production throughput.

### ADR-2: Compose service-name networking over an external CLI orchestrator
**Decision**: The orchestrator runs inside the Compose network and calls other services by hostname (`http://binding:12004`), rather than running as an external client hitting `localhost:<port>`.
**Reasoning**: This is the architecture that actually resembles a real microservices deployment, and it removes the host-port-mapping bookkeeping from the orchestrator entirely — it only ever needs to know Compose service names via `services.yaml`. The trade-off is a slightly less convenient debug loop (you can't as trivially attach a debugger to the orchestrator process), mitigated by giving every service a mapped host port anyway for manual `curl` access during development.

### ADR-3: AutoDock Vina over higher-fidelity docking tools
**Decision**: Use RDKit and Meeko preparation, AutoDock Vina docking, and ProLIF interaction fingerprints as one composite binding filter rather than separate reorderable stages.
**Reasoning**: Vina is free, well-documented, and fast enough to run per-iteration on a modest number of candidates without specialized infrastructure. Its accuracy is a known, acknowledged limitation relative to commercial tools — appropriate for a project whose goal is demonstrating pipeline architecture, not achieving state-of-the-art docking accuracy. This trade-off is stated explicitly rather than implied, per the README's validation section.

### ADR-4: SAscore/SCscore over full retrosynthesis modeling
**Decision**: Use RDKit-computable synthesizability heuristics rather than a retrosynthesis-planning model (e.g., AiZynthFinder).
**Reasoning**: Heuristic scores are near-instant and require no additional infrastructure, keeping the synthesizability filter cheap relative to docking. A full retrosynthesis model is noted as a plausible future filter stage — and because filters are additive under this architecture, it can be added without touching any other service.

### ADR-5: Molecule score history is append-only and stage-agnostic
**Decision**: Filters do not overwrite or delete prior stages' scores; every stage only appends its own `ScoreRecord`.
**Reasoning**: Since the filter chain is user-reorderable and extensible, no stage can rely on being first, last, or in any particular position. Append-only history means the pipeline's behavior is independent of what ran before, and the full run is auditable after the fact without instrumentation added after the run — the audit trail is a structural property of the data model, not a logging afterthought.

### ADR-6: Two config files instead of one
**Decision**: Pipeline definition (`pipeline.yaml`) and service location (`services.yaml`) are separate files.
**Reasoning**: See §4 above — these answer different questions (experiment design vs. deployment topology) that change on different timescales and for different reasons. This separation is also what would let the same pipeline config target a different deployment substrate (e.g., Kubernetes service DNS names) by swapping only `services.yaml`.

---

## 8. Known limitations / explicit non-goals

- **Not validated for real drug discovery decisions.** Docking and ADMET scores here come from fast, open-source approximations, not the higher-cost validated methods used in industry (see README).
- **No horizontal scaling of individual filter stages.** Each service runs as a single container; under real load, `binding` in particular would be the bottleneck and would benefit from being scaled independently — noted as a natural next step, not implemented here.
- **No authentication/authorization between services.** Appropriate for a local demonstration project; would need to be added before any multi-tenant or externally-exposed deployment.
- **Readiness, not just liveness, matters at startup.** `depends_on` in Compose only guarantees a container has started, not that its app is ready to serve requests (especially relevant for `binding` and `generator`). Every service exposes `/health`, and Compose uses `condition: service_healthy`; the orchestrator's HTTP client additionally retries with backoff on first contact with each service as defense-in-depth.
