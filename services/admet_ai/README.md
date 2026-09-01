# Standalone ADMET-AI microservice

This is the Docker-native replacement for the former Apptainer/Singularity
layout. It packages ADMET-AI v2 behind FastAPI and binds `12007:12007` through
Docker Compose. The image uses the same CPU-only Torch and ADMET-AI versions as
X-FORGE's `admet-moo` service.

## Run

```bash
docker compose up --build admet-ai
curl http://127.0.0.1:12007/health
```

Model loading happens once during application startup. Readiness returns `503`
until a model is available, so Compose cannot report a false healthy state.
`ADMET_QUEUE_COUNT` controls the number of model instances and defaults to one;
increase it only when the additional memory cost is acceptable.

## API

List property identifiers and friendly names:

```bash
curl http://127.0.0.1:12007/properties
```

Predict every property for one molecule:

```bash
curl -X POST http://127.0.0.1:12007/smi \
  -H 'Content-Type: application/json' \
  -d '{"smiles":"CCO"}'
```

Select properties by canonical ID, case-insensitive ID, or friendly slug:

```bash
curl -X POST http://127.0.0.1:12007/smi \
  -H 'Content-Type: application/json' \
  -d '{"smiles":"CCO","property":["QED","aqueous_solubility","hERG"]}'
```

Upload one SMILES per line:

```bash
curl -X POST \
  -F 'file=@services/admet_ai/smiles_list.txt' \
  'http://127.0.0.1:12007/upload_smi?property=QED&property=hERG'
```

The original `/smi`, `/upload_smi`, and `property` request names are retained.
`/live` verifies the web process; `/health` verifies that at least one model
loaded successfully.

## Relationship to `admet-moo`

This container is a standalone prediction API for external scripts. The
existing `admet-moo` image currently embeds its own ADMET-AI model because it
also performs Tier 2 gating and Tier 5 optimization. Starting `admet-ai` is not
required for the current orchestrated pipeline and will load an additional
model copy. A later change can make `admet-moo` consume this API if a single
shared model process is preferred.

## Tests

Tests replace the expensive model with a deterministic fake:

```bash
python -m pip install -r requirements-dev.txt
pytest -q
```
