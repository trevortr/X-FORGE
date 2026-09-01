# X-FORGE

**eXtensible Feedback-Optimized Reiterative Generation Engine for Hit-to-Lead Engineering**

> X-FORGE is an independent open-source project and is not affiliated with
> Cresset's Forge molecular-modeling suite.

X-FORGE is a containerized, configuration-driven molecular-design funnel. It
starts from known hits, generates related molecules with REINVENT4 Mol2Mol,
records every scientific decision as append-only molecule provenance, and feeds
selected leads into the next iteration.

The implemented Tier 0-5 workflow is:

```text
REINVENT4 sampling
  -> Tier 0 desirability reward
  -> Tier 1 2D/physchem, liabilities, and route viability
  -> Tier 2 ML/DL ADMET screening and transition gate
  -> Tier 3 conformer ensemble, docking, interactions, strain, selectivity
  -> Tier 4 validated FEP/MM-GBSA/alchemical and MD evidence
  -> Tier 5 NSGA-III reference-direction selection, scaffold diversity, batches
  -> selected leads become the next iteration's seeds
```

The existing runnable Sildenafil/1TBF workflow remains the default in
`config/pipeline.yaml`. The complete funnel is provided separately in
`config/pipeline.tiered.example.yaml` because target-specific QSAR labels,
retrosynthesis evidence, off-target structures, and high-fidelity physics
results must not be silently replaced with fabricated values. Endpoint units
and thresholds in that template must also be reviewed for the selected model.

## Services

| Compose service | Tier and role | Host port | Lifecycle |
|---|---|---:|---|
| `generator` | REINVENT4 Mol2Mol generation | `12000` | Resident API |
| `admet-moo` | Tier 2 ADMET screen and Tier 5 portfolio selection | `12001` | Resident API |
| `synthesizability` | Optional RA-Score/SAscore nonlinear gate | `12002` | Resident API |
| `policy-scoring` | Tier 0 QSAR/QED/SA/cLogP/MW reward | `12003` | Resident API |
| `binding` | Tier 3 conformers, Vina/ProLIF, strain, off-targets | `12004` | Resident API |
| `physchem` | Tier 1 rules, alerts, pKa evidence, route viability | `12005` | Resident API |
| `physics` | Tier 4 external physics/MD result validation | `12006` | Resident API |
| `admet-ai` | Standalone ADMET-AI prediction API for external clients | `12007` | Optional resident API |
| `orchestrator` | Executes one configured feedback run | None | One-shot job |
| `visualizer` | Read-only NetworkX/Matplotlib run explorer | `12010` | Resident web app |

Published ports bind to `127.0.0.1`; services communicate inside Compose by
hostname.

## Scientific stages

### Tier 0: generative reward

The orchestrator asks REINVENT for an oversampled pool, then `policy-scoring`
calculates a target-specific Morgan-fingerprint k-nearest-neighbor affinity
surrogate plus QED, SAscore, cLogP, and molecular weight. Each metric is mapped
through a configurable continuous piecewise-linear desirability curve and
combined exactly as:

```text
D = exp(sum(w_i * log(d_i)) / sum(w_i))
  = (product(d_i ^ w_i)) ^ (1 / sum(w_i))
```

Zero desirability produces `D = 0`. The highest scoring configured number of
molecules continues through the funnel, and later selected leads guide the next
Mol2Mol iteration. This is reward-guided iterative sampling; it does not mutate
or retrain the REINVENT prior.

### Tier 1: fast 2D and physicochemical filtering

`physchem` computes Lipinski and Veber descriptors, formal charge, and heavy
atom count. It applies RDKit PAINS A/B/C and Brenk catalogs, explicit reactive
electrophile/soft-warhead SMARTS (unless the project is covalent), and a basic
pKa gate when upstream pKa evidence is required.

Synthetic viability may be established by any configured evidence source:

- externally generated ASKCOS/AiZynthFinder-style route results keyed by
  molecule ID or SMILES;
- all BRICS synthons matching a supplied commercial building-block catalog; or
- a configured reaction SMARTS product template matching the molecule.

Route confidence, step count, and shared intermediate identifiers remain in the
molecule metadata for final ranking and synthesis batching.

### Tier 2: ADMET surrogate transition gate

`admet-moo` exposes the shared `/score` and `/filter` contract for a mid-funnel
ADMET screen. ADMET-AI supplies LogS, microsomal/hepatocyte clearance or
half-life, Caco-2/MDCK permeability, P-gp risk, hERG risk, and CYP3A4/2D6/2C9
risks. Configured exact measurements such as P-gp efflux ratio or hERG pIC50,
when present in prior score evidence, override model risk probabilities.

Threshold-qualified candidates are Pareto-ranked and optionally truncated by
`max_candidates` before 3D work. ADMET-AI's `Caco2_Wang` value is consumed on
its raw `log10(Papp in cm/s)` scale, so `min_log_papp: -6.0` represents
`Papp > 10^-6 cm/s`. The model schema currently defaults this threshold to
`0.0`; project configurations using raw `Caco2_Wang` predictions must override
that impractical default. Classification probabilities remain probabilities;
the service does not relabel them as efflux ratios or pIC50 values.

### Tier 3: structure-based evaluation

`binding` keeps pose-dependent operations together:

1. generate an ETKDGv3 conformer ensemble and MMFF/UFF-minimize it;
2. retain the lowest free-ligand energy and prepare with Meeko;
3. dock with AutoDock Vina and reconstruct the best bound pose;
4. calculate internal strain as `E_bound - E_lowest_free` and apply the
   configured 4-6 kcal/mol-style limit;
5. fingerprint ProLIF contacts and enforce critical interaction groups; and
6. optionally dock homologous off-targets and record selectivity gaps.

The service also retains docking score, ligand efficiency, and its explicitly
named Vina-derived LipE proxy.

### Tier 4: high-fidelity physics evidence

`physics` is a strict adapter for results from an actual FEP+, MM-GBSA, or
OpenFE/alchemical workflow and its MD analysis. For each molecule it requires a
method, binding free energy, ligand RMSD, and key-contact persistence. It applies
the default strict gates `RMSD < 2.0 A` and contact persistence `> 0.70`, plus
optional binding-energy, residence-time, off-target, and top-k constraints.

This service intentionally does not estimate free energy or trajectory metrics
from a SMILES string. Missing, non-finite, or unapproved evidence rejects the
molecule and records the reason.

### Tier 5: final Pareto portfolio

The final selector can still use knee-point, desirability/geometric mean, or
hypervolume contribution. The new `nsga3` method first performs Pareto
non-dominated sorting, associates Front 1 with Das-Dennis reference directions,
and uses reference-direction niches to order a fixed candidate set.

The tiered configuration activates five objectives inherited from upstream
evidence:

- minimize target binding free energy;
- maximize the requested `target - off-target` free-energy gap;
- minimize microsomal intrinsic clearance;
- minimize hERG pIC50; and
- minimize route steps penalized by low retrosynthesis confidence.

When Tier 4 is skipped, `docking_affinity` and `docking_selectivity_gap` provide
explicit lower-cost Tier 3 alternatives.

Front 1 is clustered with Butina using Morgan-fingerprint Tanimoto distance
(`0.4` by default). Round-robin cluster selection prevents one chemotype from
filling the portfolio. Selected compounds receive a synthesis batch from a
shared intermediate ID when available, otherwise from their Murcko scaffold.

Note that for conventional negative binding free energies, many programs define
a favorable selectivity margin as `off-target - target`. X-FORGE records that
conventional value as well, but the Tier 5 property preserves the explicitly
requested `target - off-target` definition and maximize direction.

## Orchestration and results

All scientific filters implement:

```text
POST /score   append one immutable ScoreRecord
POST /filter  partition the already-scored population
```

The orchestrator reads `config/services.yaml`, a pipeline YAML, and the selected
target YAML. It calls services in declared order and writes atomic checkpoints:

```text
results/<run-name>/
|-- iteration_001.json
|-- iteration_002.json
`-- run.json
```

Score records are append-only. This retains repeated observations across stages
and iterations rather than overwriting them. Missing molecule IDs are derived
from the first 16 hexadecimal characters of the stored SMILES SHA-256 digest;
targets may instead provide an explicit stable ID.

## Quick start

Prerequisites are Docker with Compose and the REINVENT Mol2Mol prior at
`models/reinvent/mol2mol_medium_similarity.prior`.

Run the checked-in default pipeline:

```bash
XFORGE_RUN_NAME=sildenafil-demo \
  docker compose up --build --abort-on-container-exit \
  --exit-code-from orchestrator orchestrator
```

If `XFORGE_RUN_NAME` is omitted, the result directory uses the target slug and a
UTC timestamp. To use the full tiered template, first supply its explicitly
marked target-specific inputs. Alternate checked-in configurations can be run
without replacing the default file by overriding the one-shot command:

```bash
XFORGE_RUN_NAME=serotonin-sert-demo \
  docker compose run --rm orchestrator \
  python -m app.main \
  --pipeline /config/pipeline.serotonin_sert.yaml \
  --services /config/services.yaml
```

The Compose definition currently declares every orchestrated scientific API as
an orchestrator dependency. A pipeline that omits Tier 4 performs no physics
scoring, although the lightweight `physics` evidence-validation API is still
started by Compose.

Ten additional configurations, ranging from generation-only through
high-fidelity physics, are indexed in
[config/examples/README.md](config/examples/README.md). The recommended
physics-optional starting point is
[`07_low_cost_no_physics.yaml`](config/examples/07_low_cost_no_physics.yaml).
The repository also includes runnable Sildenafil/PDE5 (1TBF), ibuprofen/COX-2
(4PH9), and serotonin/SERT (7LIA) target assets. The serotonin configuration is
a six-iteration, 50-candidate physics-free example; its single affinity label
is a local redocking score, not an experimentally validated SERT QSAR model.

Start the visualizer independently:

```bash
docker compose up --build -d visualizer
```

Open `http://localhost:12010`. The fixed-size graph viewport scrolls internally,
so zooming never lengthens the browser page. Clicking a molecule expands or
collapses its children; hovering shows provenance, score history, and an
RDKit-rendered 2D structure. **Reveal whole graph** displays all nodes,
**Show all edges** restores cycles and secondary parents hidden by default, and
**Show SMILES labels** opts into labels that are hidden for legibility.

The toolbar supports zoom, fit, four-way pan, reversible horizontal/vertical
spacing, and view reset. Keyboard equivalents are `+`/`-` (zoom), `WASD`
(pan), `F` (fit), `R` (reset view), left/right arrows (narrower/wider), and
down/up arrows (shorter/taller). Both `+` and its unshifted `=` key zoom in.

## Repository layout

```text
X-FORGE/
|-- config/
|   |-- examples/
|   |-- pipeline.yaml
|   |-- pipeline.tiered.example.yaml
|   |-- pipeline.serotonin_sert.yaml
|   |-- services.yaml
|   `-- targets/
|-- libs/schemas/
|-- models/reinvent/
|-- services/
|   |-- generator/
|   |-- admet_ai/
|   |-- policy_scoring/
|   |-- physchem/
|   |-- admet_moo/
|   |-- binding/
|   |-- physics/
|   |-- synthesizability/
|   |-- orchestrator/
|   `-- visualizer/
|-- targets/
|-- tests/integration/
|-- results/
|-- docker-compose.yml
`-- ARCHITECTURE.md
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for contracts, data flow, evidence
boundaries, and known limitations.

## License

[MIT](LICENSE)
