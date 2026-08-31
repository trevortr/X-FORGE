# Synthesizability filter

This service is the inexpensive synthetic-accessibility gate that runs before
docking. It evaluates each molecule with the pretrained ChEMBL ECFP-count
[RA-Score](https://github.com/reymond-group/RAscore) XGBoost model and RDKit's
implementation of the Ertl SAscore, preserving both raw values in the molecule's
append-only score history.

The two metrics have opposite scales, so the activation first maps them to
desirabilities in `(0, 1]`:

```text
r = clamp(RA-Score, epsilon, 1)
s = clamp((sascore_worst - SAscore) / (sascore_worst - sascore_best), epsilon, 1)
```

It then calculates the weighted generalized power mean with `p = -2` and applies
a sigmoid gate:

```text
M = ((w_ra * r^-2 + w_sa * s^-2) / (w_ra + w_sa))^(-1/2)
activation = sigmoid(gate_steepness * (M - gate_midpoint))
```

The negative exponent makes the weaker metric dominate without turning either
metric into an absolute hard gate. A molecule passes when `activation >=
min_activation`. Every constant and intermediate value is present in the request
or result JSON, so a filtering decision is reproducible.

## API

- `GET /live` checks that the HTTP process is responsive.
- `GET /health` loads the actual RA-Score model and reports runtime versions.
- `POST /score` appends one `synthesizability` score record per molecule.
- `POST /filter` partitions an already-scored population without recomputing it.

The service binds container port `12002` and Compose exposes it only on
`127.0.0.1:12002`.
