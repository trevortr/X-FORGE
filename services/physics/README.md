# Physics evidence service

This Tier 4 service validates and gates externally produced FEP+, MM-GBSA, or
OpenFE/alchemical free energies and MD trajectory analyses. It binds port
`12006` and implements the shared `/score` and `/filter` contract.

`results_path` must reference JSON keyed by molecule ID or SMILES:

```json
{
  "molecule-id": {
    "method": "openfe_alchemical",
    "binding_free_energy_kcal_mol": -9.2,
    "off_target_binding_free_energy_kcal_mol": -6.1,
    "ligand_rmsd_angstrom": 1.3,
    "key_contact_persistence": 0.82,
    "protocol": "project-v3",
    "engine_version": "1.7",
    "trajectory_id": "md-0042"
  }
}
```

Defaults require RMSD strictly below `2.0 A` and contact persistence strictly
above `0.70`. This adapter does not infer high-fidelity values from docking or
SMILES; missing or malformed evidence is rejected and audited.

```bash
PYTHONPATH=. pytest -q
```
