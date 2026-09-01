# Policy-scoring service

This Tier 0 service ranks an oversampled REINVENT pool before the main filter
chain. It computes a target-specific Morgan kNN affinity surrogate, QED,
SAscore, cLogP, and molecular weight, maps them through continuous
piecewise-linear desirability curves, and combines them with the configured
weighted geometric mean.

The service implements `GET /live`, `GET /health`, `POST /score`, and
`POST /filter` on port `12003`. `/score` appends `policy_scoring` evidence;
`/filter` partitions using that immutable decision. `top_k` is injected by the
orchestrator so an oversampled pool returns to `candidates_per_iteration`.

At least one target-specific affinity training example is mandatory. More
representative, consistently measured labels are strongly preferred because
the built-in surrogate is intentionally simple and exposes no hidden global
model.

```bash
PYTHONPATH=. pytest -q
```
