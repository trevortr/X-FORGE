# Binding service

The Tier 3 binding service keeps ordered, pose-dependent work inside one API on
port `12004`:

1. RDKit ETKDGv3 conformer-ensemble generation.
2. MMFF/UFF minimization and selection of the lowest free-ligand energy.
3. Meeko ligand preparation.
4. AutoDock Vina target and optional off-target docking.
5. Reconstruction of the best target pose and internal-strain calculation as
   `max(0, E_bound - E_lowest_free)`.
6. ProLIF interaction fingerprinting and essential-contact verification.
7. Combined affinity, efficiency, LipE-proxy, strain, interaction, and optional
   selectivity gating.

The service exposes `GET /live`, `GET /health`, `POST /score`, and
`POST /filter`. `/score` docks once and appends an immutable `binding` record;
`/filter` only partitions that population.

Target-specific parameters include receptor paths, docking box, conformer
count/pruning, Vina options, `max_internal_strain_kcal_mol`, critical
interactions, and an `off_targets` list with a receptor and box per homolog.
Both target-minus-off-target and off-target-minus-target values are retained so
the free-energy sign convention remains auditable.

The Vina-derived pKd and LipE values are proxies, not experimental affinities.
The force-field energy difference is an internal-strain approximation, and the
rigid-receptor docking protocol still requires target-specific validation.

```bash
python -m pip install -r requirements-dev.txt
PYTHONPATH=. pytest -q
```
