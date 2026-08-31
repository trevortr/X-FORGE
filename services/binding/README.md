# Binding filter

The binding service is one composite X-FORGE filter. It keeps the scientifically
ordered and tightly coupled pose workflow inside a single service boundary:

1. RDKit parses the SMILES, adds hydrogens, embeds an ETKDGv3 conformer, and
   minimizes it with MMFF or UFF.
2. Meeko assigns AutoDock atom types, charges, and rotatable bonds.
3. AutoDock Vina docks the ligand into a configured receptor box.
4. Meeko reconstructs chemically typed RDKit poses and ProLIF fingerprints
   their protein contacts.
5. The service calculates Vina score, ligand efficiency, a pKd/LipE proxy, and
   configurable critical-interaction coverage before applying every enabled
   gate.

The Vina-derived pKd and LipE values are explicitly named proxies; they are not
experimental affinities.

## API

The service binds host/container port `12004` and implements the shared filter
contract:

```text
GET  /live
GET  /health
POST /score
POST /filter
```

`/score` performs docking once and appends an immutable `binding` score record.
It also adds a `binding` metadata object containing the observed ProLIF contacts
or a molecule-specific preparation error. `/filter` only partitions that
already-scored population, so it does not repeat docking or change score
history.

Binding parameters are target-specific and live under the stage entry in
`config/pipeline.yaml`. Supported gates are `max_vina_score`,
`min_ligand_efficiency`, `min_lipe_proxy`, and critical interaction groups.
Each group names a residue such as `ARG120.A` and one or more accepted ProLIF
interaction types. `critical_mode` controls whether all groups or any group
must match.

## Included COX-2 target

The checked-in target assets under `targets/cox2_4ph9/` derive from RCSB PDB
4PH9, the 1.81 Å structure of S-ibuprofen bound to murine COX-2. Meeko prepared
chain A as a rigid receptor, using the highest-occupancy alternate conformers.
The 22 Å docking box is centered on the crystallographic ibuprofen site.

The default four-iteration pipeline uses deliberately permissive gates so it
functions as an integration smoke test. Those thresholds demonstrate data flow
and must not be interpreted as a validated COX-2 screening protocol.

## Tests

```bash
PYTHONPATH=services/binding pytest services/binding/tests
PYTHONPATH=. pytest tests/integration/test_four_iteration_binding_loop.py
```
