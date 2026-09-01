# X-FORGE Architecture

This document describes the implemented service boundaries, scientific data
flow, evidence contracts, and deployment lifecycle. The top-level
[README](README.md) is the operational introduction.

## 1. System overview

X-FORGE is a synchronous feedback pipeline on a private Docker Compose network.
A one-shot orchestrator calls resident scientific APIs and writes durable JSON
checkpoints to a shared result directory.

```text
                               pipeline + services + target YAML
                                             |
                                             v
                                      +--------------+
                                      | orchestrator |
                                      | one run/job  |
                                      +------+-------+
                                             |
                                             v
 generator -> policy-scoring -> physchem -> admet-moo:/score
  Tier 0         Tier 0          Tier 1        Tier 2
                                             |
                                             v
                      binding -> physics -> admet-moo:/optimize
                       Tier 3      Tier 4          Tier 5
                                             |
                                             +---- selected leads
                                                   become new seeds

 results/<run-name>/*.json -> read-only visualizer
```

No scientific service imports another service's implementation. Shared
`Molecule` and `ScoreRecord` envelopes live under `libs/schemas`; service-specific
request options and metadata remain local.

### Deployment topology

| Service | Compose hostname | Port | Lifecycle |
|---|---|---:|---|
| Generator | `generator` | `12000` | Resident API |
| ADMET screen and MOO | `admet-moo` | `12001` | Resident API |
| Legacy synthesizability | `synthesizability` | `12002` | Resident API |
| Policy scoring | `policy-scoring` | `12003` | Resident API |
| Binding | `binding` | `12004` | Resident API |
| Physchem | `physchem` | `12005` | Resident API |
| Physics evidence | `physics` | `12006` | Resident API |
| Standalone ADMET-AI | `admet-ai` | `12007` | Optional resident API |
| Orchestrator | `orchestrator` | None | One-shot job |
| Visualizer | `visualizer` | `12010` | Resident read-only UI |

Host ports bind to `127.0.0.1`; internal calls use Compose DNS names. Compose
health checks establish API readiness, while target- and run-specific files are
validated on scoring requests.

`admet-ai` is a Docker-native standalone prediction endpoint retained for
external consumers. It is not an orchestrator dependency: `admet-moo` still
loads its own model for Tier 2 and Tier 5, so starting both containers consumes
memory for two model instances.

## 2. Configuration model

Configuration separates experimental intent from deployment location:

- `config/services.yaml` maps logical service names to internal URLs.
- `config/pipeline.yaml` is the backward-compatible, runnable reference flow.
- `config/pipeline.tiered.example.yaml` demonstrates the full Tier 0-5 flow.
- `config/examples/` contains ten schema-validated workflow variants and an
  evidence-requirement index.
- `config/targets/*.yaml` contains target identity and starting hits.
- `targets/` contains prepared structural assets mounted into `binding`.
- `results/` contains checkpoints and external Tier 4 result evidence.

The generator reward is optional. When enabled, `candidates_per_iteration` is
multiplied by `generator.reward.pool_multiplier`; Tier 0 then sets `top_k` back
to the original budget. Intermediate stages retain their declared order and use
the existing generic filter contract.

The full shape is:

```yaml
generator:
  reward:
    service: policy_scoring
    pool_multiplier: 4
    parameters: {...}

pipeline:
  - physchem: {...}
  - admet_screen: {...}
  - binding: {...}
  - physics: {...}

admet_moo:
  properties:
    - binding_free_energy
    - selectivity_gap
    - metabolic_clearance
    - herg_pic50
    - synthetic_feasibility
  selection:
    method: nsga3
    nsga3_reference_partitions: 4
    diversity:
      enabled: true
      tanimoto_distance_threshold: 0.4
```

Startup validation resolves the target path, rejects malformed stages, and
requires URLs for the generator, all configured filters, the optional reward,
and final selector. Existing configurations without a reward or new services
retain their previous behavior.

## 3. HTTP contracts

### Shared scoring/filter contract

`policy-scoring`, `physchem`, `admet-moo` Tier 2, `binding`, `physics`, and the
legacy `synthesizability` service expose:

```text
POST /score
  request:  {molecules: [Molecule, ...], parameters: {...}}
  response: {molecules: [Molecule with one appended ScoreRecord, ...]}

POST /filter
  request:  {molecules: [already-scored Molecule, ...], parameters: {...}}
  response: {passed: [...], rejected: [...]}
```

`/filter` partitions only and requires the latest score to belong to that
service. This preserves rejected evidence and prevents a stale decision from
being reused.

### Generator contract

```text
POST /generate
  request:  seeds, candidates per seed, strategy, temperature, random seed
  response: generated SMILES, stable IDs, parents, similarity, NLL, model
```

### Final optimization contract

```text
GET  /properties
POST /optimize
  request:  molecules, top_k, active properties, selection configuration
  response: evaluated population, Front 1, selected portfolio, metadata
```

All services expose `/live` and `/health` endpoints.

## 4. Molecule provenance

The stable shared contract remains:

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

Pydantic permits service-specific metadata such as desirabilities, alerts,
routes, interactions, physics protocol IDs, Pareto rank, clusters, and synthesis
batches. IDs are the first 16 hexadecimal characters of SHA-256 over the stored
SMILES.

The orchestrator rejects service responses that change a scored population,
overlap or omit a filter partition, rewrite score history, return duplicate
generated IDs, or reference unknown parents. A ledger retains the newest
append-only snapshot while iteration files retain historical occurrences and
parent edges.

## 5. Scientific stages

### 5.1 Tier 0: reward-guided generation

REINVENT4 v4.8 performs Mol2Mol sampling from the mounted prior. The optional
`policy-scoring` stage derives five raw metrics:

- target affinity from a target-specific Morgan/ECFP kNN QSAR surrogate;
- RDKit QED;
- RDKit SAscore;
- RDKit cLogP; and
- molecular weight.

Each configured curve is validated to have strictly increasing x coordinates
and linearly interpolated continuously between its points. Outside the domain,
the endpoint desirability is used. Positive weights are mandatory. The
composite is evaluated stably in log space:

```text
D = exp(sum_i(w_i log(d_i)) / sum_i(w_i))
```

Any zero component makes the product and `D` zero. Thresholding and top-k are
both supported. The score affects which molecules advance and therefore which
leads seed the next iteration; no model weights are updated.

### 5.2 Tier 1: 2D, liability, and synthesis viability

`physchem` calculates molecular weight, cLogP, H-bond donors/acceptors, TPSA,
rotatable bonds, formal charge, and heavy atom count. These implement Lipinski,
Veber (`TPSA <= 140 A^2`, rotatable bonds `<= 10` by default), charge `[-1, 1]`,
and configured heavy-atom gates.

The service combines RDKit's PAINS A/B/C and Brenk filter catalogs with explicit
SMARTS for acyl/sulfonyl halides, isocyanates, isothiocyanates, epoxides,
aziridines, Michael acceptors, and aldehydes. Projects may allow covalent
warheads explicitly. Basic-site alerts are always recorded; exact pKa bounds
are gated when `require_pka_prediction` is enabled and the configured molecule
field is present.

Route viability passes when at least one configured route source succeeds:

1. external route evidence meets confidence and step-count limits;
2. all BRICS synthons occur in the supplied building-block catalog; or
3. the product side of a configured reaction SMARTS matches.

External route JSON is keyed by molecule ID or SMILES and may include
`route_confidence`, `route_steps`, and `shared_intermediate_id`. X-FORGE does
not claim that a substructure/template match is a complete retrosynthesis.

### 5.3 Tier 2: ADMET surrogate gate

ADMET-AI performs one batch prediction. The screen consumes:

| Endpoint | Default source or evidence | Default interpretation |
|---|---|---|
| Solubility | `Solubility_AqSolDB` | require LogS `> -4` |
| Microsomal clearance | `Clearance_Microsome_AZ` | optional upper gate |
| Hepatocyte clearance | `Clearance_Hepatocyte_AZ` | optional upper gate |
| Half-life | `Half_Life_Obach` | optional lower gate |
| Permeability | `Caco2_Wang` or configured MDCK field | require native log Papp `> 0` |
| P-gp | exact efflux field, else `Pgp_Broccatelli` | ratio `< 2.5` or risk gate |
| hERG | exact pIC50 field, else `hERG` | pIC50 `< 5` or risk gate |
| CYPs | Veith 3A4, 2D6, and 2C9 | probability upper gate |

Existing numeric molecule fields and prior `ScoreRecord.values` override model
columns. This allows validated exact endpoints to flow through the same data
type without changing interfaces. Model risk classifications remain named as
probabilities when no exact ratio or potency exists.

Continuous threshold-centered desirabilities form a minimization matrix for
PyMOO non-dominated sorting. Hard-gate survivors are ordered by Pareto rank and
geometric mean, then optionally capped by `max_candidates` before Tier 3.

### 5.4 Tier 3: structure-based evaluation

`binding` is one service because each operation consumes the structures or
poses produced by the previous operation:

1. ETKDGv3 embeds a configurable conformer ensemble.
2. MMFF, or UFF fallback, minimizes every conformer.
3. The lowest free-ligand-energy conformer is prepared by Meeko.
4. Vina docks against the target and optional homologous off-targets.
5. The best target pose is reconstructed and force-field evaluated.
6. `max(0, E_bound - E_lowest_free)` is recorded as internal strain.
7. ProLIF fingerprints contacts and checks essential interaction groups.

The gate can combine Vina score, ligand efficiency, LipE proxy, critical
interactions, internal strain, and requested target/off-target selectivity.
Receptor/Vina contexts are cached and locked because they hold mutable ligand
state. Failures reject only the affected molecule unless target configuration
itself is invalid.

### 5.5 Tier 4: high-fidelity evidence adapter

High-fidelity free energies and MD observables require prepared chemical
systems, protocols, trajectories, compute resources, and often licensed or
separately installed engines. `physics` therefore validates and gates real
result evidence rather than synthesizing it from lower-fidelity scores.

Its JSON source is keyed by molecule ID or SMILES. Each entry requires:

```json
{
  "method": "openfe_alchemical",
  "binding_free_energy_kcal_mol": -9.2,
  "ligand_rmsd_angstrom": 1.3,
  "key_contact_persistence": 0.82
}
```

Allowed methods are `fep_plus`, `mm_gbsa`, and `openfe_alchemical`. Optional
fields include off-target free energy, uncertainty, residence-time proxy,
protocol, engine version, and trajectory ID. Defaults require ligand RMSD
strictly below `2.0 A` and key-contact persistence strictly above `0.70`.
Missing, non-finite, or unapproved evidence produces a molecule-level rejection.

When off-target energy is available, both signs are retained:

```text
requested gap    = target - off-target
conventional gap = off-target - target
```

This preserves the requested downstream objective while making the sign choice
auditable under the usual negative binding-free-energy convention.

### 5.6 Tier 5: Pareto ranking, diversity, and batching

The original five default `ADMETProperty` subclasses remain unchanged for
backward compatibility. Five opt-in properties read evidence accumulated by
the funnel:

| Property | Goal | Evidence |
|---|---|---|
| `binding_free_energy` | minimize | Tier 4 target free energy |
| `selectivity_gap` | maximize | requested target-minus-off-target gap |
| `metabolic_clearance` | minimize | Tier 2 microsomal CLint |
| `herg_pic50` | minimize | exact Tier 2 evidence |
| `synthetic_feasibility` | minimize | `steps + 5(1 - confidence)` |

All properties still inherit from `ADMETProperty`; no molecule or optimizer
datatype was replaced.

Physics-optional pipelines can select `docking_affinity` and
`docking_selectivity_gap` instead. These consume Tier 3 Vina evidence and stay
explicitly distinct from the higher-fidelity Tier 4 free-energy objectives.

For `selection.method: nsga3`, PyMOO non-dominated sorting identifies Front 1.
Normalized front points are associated with Das-Dennis reference directions,
and sparse reference-direction niches are favored when ordering the fixed
portfolio. This is NSGA-III-style survival selection over generated candidates,
not an evolutionary optimizer that mutates molecules inside ADMET-MOO.

When diversity is enabled, Front 1 Morgan fingerprints are clustered by Butina
at the configured Tanimoto-distance threshold. A round-robin across clusters
selects diverse representatives. `shared_intermediate_id` becomes the synthesis
batch when available; the Murcko scaffold is the fallback batch key.

The existing knee-point, weighted desirability, and hypervolume-contribution
methods remain available.

## 6. Orchestration lifecycle

One orchestrator invocation:

1. validates configuration and writes a `running` `run.json`;
2. waits for configured service readiness;
3. generates either the normal budget or an oversampled Tier 0 pool;
4. appends the generator score and records each `/score` and `/filter` result;
5. stops cleanly if no candidates remain;
6. calls Tier 5 with all upstream evidence still attached;
7. writes the iteration atomically and feeds selected leads forward; and
8. marks the run completed or failed and exits.

Early completion occurs when generation is empty, all candidates are filtered,
or final selection returns no lead. A run directory is set by
`XFORGE_RUN_NAME`; otherwise the target slug and high-resolution UTC timestamp
form the name.

## 7. Visualization

The visualizer mounts `results/` read-only. NetworkX builds lineage and
Matplotlib produces SVG layers; browser JavaScript manages visibility. Initial
hits appear first, clicking toggles descendants, whole-graph reveal is
available, and cycles/secondary parents remain hidden until **Show all edges**
is enabled. Leaf nodes are square.

## 8. Reproducibility and evidence boundaries

| Artifact | Handling |
|---|---|
| REINVENT prior | supplied locally and mounted read-only |
| REINVENT runtime | pinned Compose build reference |
| RA-Score model | pinned and checksum-verified at image build |
| ADMET-AI | package-pinned model runtime |
| receptor assets | versioned target files mounted read-only |
| affinity labels | target-specific Tier 0 configuration |
| route evidence | external result file, catalog, or templates |
| FEP/MD results | external result file with method/protocol provenance |

Random seeds are configurable for REINVENT and Vina; conformer seeds derive
stably from SMILES. Numerical reproduction can still depend on model artifacts,
CPU/library implementations, receptor preparation, and external protocols.

## 9. Known limitations

- X-FORGE is an integration and decision-support platform, not a validated
  experimental drug-discovery system.
- Tier population ranges describe funnel intent; the current synchronous JSON
  APIs and single-host services should be chunked or replaced with distributed
  workers for million-molecule campaigns.
- Tier 0 is selection-guided Mol2Mol feedback and does not train REINVENT policy
  weights.
- Morgan kNN affinity predictions are only as useful as the configured labels
  and their applicability domain.
- PAINS/Brenk/warhead matches and pKa checks require expert review; alerts are
  not universal activity or safety verdicts.
- Building-block and reaction-template checks are rapid feasibility evidence,
  not complete route planning.
- ADMET-AI fallback values for P-gp and hERG are classification probabilities,
  not efflux ratios or pIC50 measurements.
- Tier 3 uses a rigid receptor and force-field strain approximation. Its LipE is
  Vina-derived, not experimental.
- Tier 4 does not launch commercial FEP+, OpenFE, MD, or MM-GBSA jobs. It
  validates separately produced results so the pipeline never fabricates
  high-fidelity evidence.
- The requested target-minus-off-target gap and maximize direction are retained
  exactly, although the opposite sign is conventional for negative free
  energies.
- There is no authentication, queue, distributed scheduler, or automatic resume.

## 10. Verification

Unit and service suites cover desirability interpolation/geometric means,
liability and route gates, ADMET endpoints and transition pruning, conformer
strain/selectivity metrics, physics evidence validation, NSGA-III portfolio
selection, diversity/batching, configuration compatibility, and append-only
orchestration. The deterministic top-level Tier 0-5 integration test verifies
oversampling and exact stage order without presenting mocked values as
scientific validation.
