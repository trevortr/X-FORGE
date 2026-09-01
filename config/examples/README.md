# Example pipeline configurations

These ten examples are starting points, not validated discovery protocols. All
paths are relative to this directory, so they can be passed directly to the
orchestrator. Every run still requires the local REINVENT prior.

| File | Demonstrates | External evidence |
|---|---|---|
| `01_minimal_generation.yaml` | Small generation-only loop and knee selection | None |
| `02_reward_guided_exploration.yaml` | Tier 0 oversampling, custom curves, weighted reward | Replace illustrative affinity labels |
| `03_conservative_synthesis.yaml` | Beam search and strict legacy RA/SA gate | None |
| `04_fast_2d_oral.yaml` | Lipinski/Veber, alerts, and an amide reaction template | None |
| `05_covalent_project.yaml` | Explicitly allowing covalent warheads | None |
| `06_admet_only_stringent.yaml` | Strict Tier 2 screen without docking | None |
| `07_low_cost_no_physics.yaml` | Tier 0-3 loop with docking-based final objectives | Replace illustrative affinity label |
| `08_interaction_constrained_docking.yaml` | Essential contact and ligand-strain gates | Validate the interaction protocol |
| `09_off_target_negative_design.yaml` | Target/off-target docking and diverse NSGA-III portfolio | Replace the illustrative off-target |
| `10_high_fidelity_physics.yaml` | Complete external route/FEP/MD evidence path | Route and physics JSON files |

For example, run the low-cost configuration with:

```bash
docker compose run --rm \
  -e XFORGE_RUN_NAME=low-cost-demo \
  orchestrator \
  --pipeline /config/examples/07_low_cost_no_physics.yaml \
  --services /config/services.yaml
```

Examples 1 and 3-6 use only checked-in target assets and service models.
Examples 2 and 7 contain explicitly illustrative affinity labels that must be
replaced before scientific use. Examples 8 and 9 are executable demonstrations but their
interaction/off-target choices are not validated target protocols. Example 10
will reject molecules until its external files contain results keyed by the
generated molecule IDs or SMILES.

The high-fidelity result schemas are documented in
`services/physchem/README.md` and `services/physics/README.md`.
