# ADMET-MOO service

This is the final X-FORGE stage in each iteration. It predicts ADMET endpoints
for molecules that survived the filter chain, constructs a minimization
objective matrix, uses pymoo for non-dominated sorting, and returns selected
leads from the Pareto front.

## Default objectives

Each endpoint is a concrete class inheriting from `ADMETProperty`:

| API key | ADMET-AI output | Goal | Default desirability |
|---|---|---|---|
| `bioavailability` | `Bioavailability_Ma` | maximize | predicted probability |
| `aqueous_solubility` | `Solubility_AqSolDB` | maximize | linear from 0 at -6 to 1 at -2 log(mol/L) |
| `cyp3a4_inhibition` | `CYP3A4_Veith` | minimize | 1 - predicted probability |
| `herg_blocking` | `hERG` | minimize | 1 - predicted probability |
| `dili` | `DILI` | minimize | 1 - predicted probability |

The small default panel keeps the trade-offs interpretable and exact
hypervolume practical. To add an endpoint, define one class in
`app/properties.py` and register it with `property_registry`. The predictor and
optimization engine do not need endpoint-specific changes.

These model outputs are decision-support predictions, not experimentally
validated measurements.

## Lead selection

`selection.method` controls how candidates on Pareto rank 0 are ordered:

- `knee_point` uses pymoo's high-tradeoff-point detector, then a normalized
  distance-to-ideal compromise score to rank any remaining front members.
- `desirability` computes each endpoint's desirability and ranks by weighted
  geometric mean. Optional weights must be positive.
- `hypervolume_contribution` ranks each point by the normalized hypervolume
  lost when it is removed. Reference-point coordinates are normalized and
  default to `1.1` for every active objective.

No dominated molecule is used to fill `top_k`; when the front is smaller than
`top_k`, the response contains fewer selected leads.

## API

```http
POST /optimize
Content-Type: application/json

{
  "molecules": [
    {
      "smiles": "CC(=O)OC1=CC=CC=C1C(=O)O",
      "id": "aspirin-analogue-1",
      "parent_id": "aspirin-hit",
      "iteration": 1,
      "scores": []
    }
  ],
  "top_k": 10,
  "properties": null,
  "selection": {
    "method": "desirability",
    "weights": {"herg_blocking": 2.0},
    "reference_point": null
  }
}
```

The response includes every evaluated molecule, Pareto rank 0, and selected
subsets. It also appends an `admet_moo` record to each molecule's score history.
Use `GET /properties` to inspect the active property catalog, `GET /live` for
process liveness, and `GET /health` to load and verify the ADMET-AI model.

## Run

```bash
docker compose up --build admet-moo
curl http://127.0.0.1:12001/health
```

The initial model load can take substantially longer than later health calls.
The production image explicitly installs the official CPU-only Torch wheel so
pip does not pull the much larger CUDA runtime into a CPU deployment.
It also includes the X11 and Expat runtime libraries required by the RDKit
wheel bundled through ADMET-AI's dependency tree.
For local tests, the real model is replaced by a deterministic fake:

```bash
cd services/admet_moo
python -m pip install -r requirements-dev.txt
PYTHONPATH=. pytest
```
