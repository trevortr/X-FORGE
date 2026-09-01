# ADMET-MOO service

This service has two roles on port `12001`:

- Tier 2 exposes `/score` and `/filter` for ADMET-AI surrogate screening and
  Pareto-based transition pruning before 3D work.
- Tier 5 exposes `/optimize` for final non-dominated sorting, portfolio
  selection, scaffold diversity, and synthesis batching.

## Tier 2 screen

The configurable screen uses aqueous solubility, microsomal/hepatocyte
clearance or half-life, Caco-2/MDCK permeability, P-gp, hERG, and CYP3A4/2D6/2C9.
Hard-gate survivors are ordered by Pareto rank and geometric mean, then capped
by `max_candidates` when set.

ADMET-AI provides model-native endpoints. Existing numeric `ScoreRecord.values`
or numeric molecule metadata override prediction columns, allowing exact P-gp
efflux ratio and hERG pIC50 evidence to use the same interface. If those exact
fields are absent, `Pgp_Broccatelli` and `hERG` remain explicitly named risk
probabilities; the service does not reinterpret them as ratios or potency.

`Caco2_Wang` is handled as `log10(Papp / (10^-6 cm/s))`; the default threshold
of `0` represents `Papp > 10^-6 cm/s`.

## Tier 5 properties

Every objective is an `ADMETProperty` subclass. The original default panel is
unchanged:

| Key | Goal |
|---|---|
| `bioavailability` | maximize |
| `aqueous_solubility` | maximize |
| `cyp3a4_inhibition` | minimize |
| `herg_blocking` | minimize |
| `dili` | minimize |

The full funnel opts into five evidence-backed objectives:

| Key | Goal | Source |
|---|---|---|
| `binding_free_energy` | minimize | Tier 4 target free energy |
| `selectivity_gap` | maximize | target-minus-off-target free-energy gap |
| `metabolic_clearance` | minimize | Tier 2 microsomal CLint |
| `herg_pic50` | minimize | exact hERG pIC50 evidence |
| `synthetic_feasibility` | minimize | route steps plus confidence penalty |

Physics-optional pipelines can instead use `docking_affinity` and
`docking_selectivity_gap`, which consume Tier 3 Vina evidence.

## Selection methods

- `knee_point`: PyMOO high-tradeoff points with distance-to-ideal fallback.
- `desirability`: configurable weighted geometric mean.
- `hypervolume_contribution`: normalized Front 1 contribution.
- `nsga3`: non-dominated Front 1 followed by Das-Dennis
  reference-direction/niche ordering for the fixed candidate portfolio.

When diversity is enabled, Butina clusters Front 1 using Morgan-fingerprint
Tanimoto distance and candidates are selected round-robin across clusters.
`shared_intermediate_id` is used as a synthesis-batch key, with Murcko scaffold
as fallback.

No dominated molecule fills an undersized `top_k`; fewer leads are returned
when Front 1 is smaller.

## API and tests

```text
GET  /live
GET  /health
GET  /properties
POST /score
POST /filter
POST /optimize
```

The initial ADMET-AI load can take longer than later health checks. The image
uses CPU Torch and includes the native X11/Expat libraries required by its
RDKit dependency.

```bash
python -m pip install -r requirements-dev.txt
PYTHONPATH=. pytest -q
```
