# Generator service

The first X-FORGE vertical slice generates analogues of one or more hit
molecules with REINVENT4's conditional **Mol2Mol** generator. It performs no
property optimization and no downstream filtering.

## Model choice

X-FORGE defaults to `mol2mol_medium_similarity.prior`: REINVENT4 trained this
prior on molecular pairs in the medium Tanimoto-similarity range. The model
file is intentionally not committed to Git. Download a REINVENT4 Mol2Mol prior
from the [official Zenodo model archive](https://zenodo.org/records/15641297)
and place it at:

```text
models/reinvent/mol2mol_medium_similarity.prior
```

The model can be changed with `REINVENT_MODEL_PATH`. A high-similarity or
scaffold prior can later be evaluated without changing the API.

## API

```http
POST /generate
Content-Type: application/json

{
  "seeds": [
    {"smiles": "CC(=O)OC1=CC=CC=C1C(=O)O", "id": "aspirin-hit"}
  ],
  "n_candidates_per_seed": 100,
  "strategy": "multinomial",
  "temperature": 1.0,
  "random_seed": 42
}
```

REINVENT4 may return fewer molecules than requested after invalid structures
and duplicates are removed. Each result includes its input molecule,
REINVENT4's Tanimoto similarity and negative log-likelihood, and stable IDs for
later provenance tracking.

`multinomial` is stochastic and supports the temperature control.
`beamsearch` is deterministic and generally slower.

## Health endpoints

- `GET /live` is a cheap process-liveness check.
- `GET /health` is a readiness check. It verifies the executable and model file,
then runs and caches a `reinvent --help` probe so missing native libraries are
detected before generation traffic is accepted.

The service pins SciPy explicitly because REINVENT4 4.8.24 imports
`scipy.stats` during CLI startup but does not declare SciPy in its package
metadata.

## Run

```bash
docker compose up --build generator
curl http://127.0.0.1:12000/health
```

For local service development, install REINVENT4 separately, then:

```bash
cd services/generator
python -m pip install -r requirements-dev.txt
PYTHONPATH=. pytest
uvicorn app.main:app --reload
```
