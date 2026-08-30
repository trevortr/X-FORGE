# Orchestrator service

The orchestrator is the control plane for an X-FORGE run. It reads the
experiment definition from `config/pipeline.yaml`, resolves service hostnames
from `config/services.yaml`, loads the target seed molecules, and drives the
configured feedback loop.

It is a one-shot process rather than an HTTP API: exit code `0` means the run
completed, while exit code `2` means configuration validation or a service call
failed.

## Iteration order

For every iteration the orchestrator:

1. Calls `generator /generate` with the current feedback seeds.
2. Adds a `generator` score record containing REINVENT's Tanimoto and NLL
   values and the current iteration number.
3. Calls every configured filter by service name, in YAML order: `/score`
   followed by `/filter`.
4. Retains both the passed and rejected populations in the iteration result.
5. Sends the final survivors to `admet_moo /optimize`.
6. Uses only ADMET-MOO's selected Pareto-front leads as the next iteration's
   seeds.

`candidates_per_iteration` is a total population budget. The orchestrator
divides it across the current seeds for the generator's per-seed API and trims
any rounding excess.

An empty `pipeline: []` is valid and runs generator → ADMET-MOO directly. This
is the current example because filter services have not been added yet.

## Molecule tracking

The shared `Molecule` envelope contains a stable ID, one immediate parent ID,
the iteration where the molecule was generated, and an append-only list of
`ScoreRecord` objects. The orchestrator rejects service responses that remove
or rewrite earlier scores.

Each output directory contains:

- `iteration_001.json`, etc.: seeds, all generated candidates, every filter's
  passed/rejected partition, ADMET evaluations, the Pareto front, and selected
  feedback molecules.
- `run.json`: run status, timestamps, all iterations, the final selection, and
  a deduplicated molecule catalog containing the latest history for every
  stable molecule ID observed during the run.

`run.json` is written initially and after every iteration, then atomically
replaced with the completed result. A failed service call therefore leaves a
diagnostic checkpoint rather than losing the run history.

## Run the acetaminophen example

The checked-in configuration performs three iterations with five generated
candidates per iteration and two feedback leads:

```bash
docker compose up --build \
  --abort-on-container-exit \
  --exit-code-from orchestrator \
  orchestrator
```

Results are written to `results/example_run/`. The orchestrator waits for both
fixed services to report healthy and retries transient HTTP failures with
exponential backoff.

## Tests

The top-level integration test runs three complete acetaminophen iterations
against deterministic HTTP fakes while exercising the real YAML loader,
service client, runner, lineage checks, and result writer:

```bash
python -m pip install -r services/orchestrator/requirements-dev.txt
PYTHONPATH=services/orchestrator:. pytest \
  services/orchestrator/tests tests/integration
```
