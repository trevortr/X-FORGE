# Physchem service

This Tier 1 service performs fast RDKit 2D and physicochemical gating on port
`12005`. It covers Lipinski and Veber descriptors, formal charge, heavy atom
count, PAINS A/B/C, Brenk alerts, reactive/soft-warhead SMARTS, basic-site and
optional pKa evidence, and rapid synthesis-route viability.

Retrosynthesis may be satisfied by external result JSON keyed by molecule ID or
SMILES, a commercial building-block SMILES catalog matched against every BRICS
synthon, or configured reaction SMARTS. External entries use this shape:

```json
{
  "molecule-id": {
    "route_confidence": 0.81,
    "route_steps": 4,
    "shared_intermediate_id": "core-17"
  }
}
```

The service records all alert names, route evidence, and pass flags. These are
rapid screening signals, not a substitute for expert review or a validated
retrosynthesis plan.

```bash
PYTHONPATH=. pytest -q
```
