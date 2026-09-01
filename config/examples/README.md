# Pipeline YAML reference and examples

This directory contains ten starting configurations and this field-by-field
reference for the X-FORGE pipeline YAML. The examples are executable templates,
not validated drug-discovery protocols. Thresholds, affinity labels, protein
preparation, interaction constraints, and external physics results must be
validated for the target and assay context before scientific use.

## Example index

| File | Demonstrates | External evidence or validation needed |
|---|---|---|
| `01_minimal_generation.yaml` | Small generation-only loop and knee selection | None |
| `02_reward_guided_exploration.yaml` | Tier 0 oversampling, custom curves, weighted reward | Replace illustrative affinity labels |
| `03_conservative_synthesis.yaml` | Beam search and strict legacy RA/SA gate | None |
| `04_fast_2d_oral.yaml` | Lipinski/Veber, alerts, and an amide reaction template | Validate the synthesis heuristic |
| `05_covalent_project.yaml` | Explicitly allowing covalent warheads | Confirm a covalent mechanism is intended |
| `06_admet_only_stringent.yaml` | Strict Tier 2 screen without docking | Validate endpoint calibration and thresholds |
| `07_low_cost_no_physics.yaml` | Tier 0-3 loop with docking-based final objectives | Replace illustrative affinity labels |
| `08_interaction_constrained_docking.yaml` | Essential contact and ligand-strain gates | Validate the interaction protocol |
| `09_off_target_negative_design.yaml` | Target/off-target docking and diverse NSGA-III portfolio | Replace the illustrative off-target |
| `10_high_fidelity_physics.yaml` | Complete external route/FEP/MD evidence path | Supply route and physics JSON files |

For example:

```bash
docker compose run --rm \
  -e XFORGE_RUN_NAME=low-cost-demo \
  orchestrator \
  --pipeline /config/examples/07_low_cost_no_physics.yaml \
  --services /config/services.yaml
```

## How a pipeline executes

Every iteration has a fixed outer shape:

```text
REINVENT generator
  -> optional Tier 0 reward/filter
  -> each pipeline stage in YAML order
  -> final ADMET-MOO Pareto selection
  -> selected molecules become the next iteration's seeds
```

The generator and final `admet_moo` step are implicit; do not put them in the
`pipeline:` list. Any listed stage may be omitted, including `physics`. A run
stops early if generation returns nothing, every molecule is filtered out, or
the final optimizer selects no leads. Although YAML permits arbitrary stage
order, the scientifically intended order is generally `physchem` ->
`admet_screen` -> `binding` -> `physics`; expensive evidence should only be
computed after cheaper gates have reduced the population.

Most configuration models reject unknown keys. YAML `null` disables an optional
threshold or endpoint. Paths are resolved by the service that reads them, so in
Docker configurations use container-visible paths such as `/targets/...` or
`/results/...`, not host-only paths.

## Complete top-level example

```yaml
target: ../targets/example_target.yaml
iterations: 3
candidates_per_iteration: 100
top_k_feedback: 10

generator:
  strategy: multinomial
  temperature: 1.0
  random_seed: 42

pipeline:
  - physchem:
      require_retrosynthesis: false
  - admet_screen:
      min_log_s: -4.0
      max_candidates: 1000

admet_moo:
  properties: null
  selection:
    method: knee_point
    weights: null
    reference_point: null
    nsga3_reference_partitions: 4
    diversity:
      enabled: false

http:
  timeout_seconds: 900
  max_attempts: 5
  backoff_seconds: 1

results_root: results
```

## Top-level fields

| Field | Type, default, constraints | Meaning and scientific reason |
|---|---|---|
| `target` | string, `targets/example_target.yaml` | Target YAML path, relative to the pipeline file unless absolute. It supplies the project name and one or more starting hits. |
| `iterations` | integer, `3`, 1-100 | Number of generate/filter/select feedback cycles. More iterations explore farther from the starting hits but compound model bias and compute cost. |
| `candidates_per_iteration` | integer, `10`, 1-1000 | Normal generation budget across all seeds. With Tier 0 reward enabled, REINVENT first makes this many times `pool_multiplier`, then reward scoring reduces the pool back to this budget. |
| `top_k_feedback` | integer, `3`, 1-1000 | Maximum Pareto-front leads fed into the next iteration. A narrow value exploits a few chemotypes; a larger value preserves more hypotheses. The final selector never fills the quota with dominated molecules. |
| `generator` | mapping | REINVENT mol2mol sampling controls; documented below. |
| `pipeline` | list, empty | Ordered filter-stage mappings. Each item must contain exactly one service name matching `[a-z][a-z0-9_-]*`. Empty means generation followed directly by final optimization. |
| `admet_moo` | mapping | Final Pareto objective and lead-selection controls. This step always runs after the configured stages. |
| `http` | mapping | Service timeout and retry policy. These affect robustness, not scientific scoring. |
| `results_root` | string, `results` | Parent directory for `run.json` and iteration JSON. `XFORGE_RESULTS_ROOT` or the CLI override takes precedence. |

The run subdirectory name is not a YAML field. Set `XFORGE_RUN_NAME` or the CLI
run-name option. If omitted, X-FORGE creates `<target>-<UTC timestamp>`; explicit
names may contain letters, digits, `.`, `_`, and `-` and must begin with a letter
or digit.

### Target YAML

```yaml
name: Example target
seeds:
  - smiles: CC(=O)NC1=CC=C(C=C1)O
    id: optional-stable-id
```

| Field | Type and constraints | Meaning |
|---|---|---|
| `name` | non-empty string | Human-readable project/target name used in results and the automatic run name. |
| `seeds` | list of 1-100 molecules | Initial hits supplied to REINVENT. Multiple seeds explore several starting chemotypes. |
| `seeds[].smiles` | non-empty SMILES | Molecular structure. |
| `seeds[].id` | optional string | Stable lineage identifier. If omitted, X-FORGE derives one from the SMILES. |

Additional target metadata is allowed and preserved. Molecule lineage, iteration,
and score-history fields are normally produced by the pipeline rather than
authored in a target file.

## Generator and Tier 0 reward

### `generator`

| Field | Type, default, constraints | Meaning and scientific reason |
|---|---|---|
| `strategy` | `multinomial` or `beamsearch`; `multinomial` | Multinomial sampling supports stochastic chemical exploration. Beam search favors high-probability model continuations and is more deterministic/exploitative. |
| `temperature` | float, `1.0`, 0.1-2.0 | Rescales sampling probabilities. Lower values focus on likely molecules; higher values broaden exploration and usually increase invalid or implausible proposals. Most relevant to multinomial sampling. |
| `random_seed` | integer, `42`, >= 0 | Reproducibility seed. The orchestrator adds `iteration - 1`, so each cycle is reproducible but different. |
| `reward` | mapping or `null`; `null` | Enables post-generation, in-the-loop desirability scoring. This ranks an oversampled pool before Tier 1. It filters the sampler's output; it does not retrain REINVENT weights. |

### `generator.reward`

| Field | Type, default, constraints | Meaning |
|---|---|---|
| `service` | string, `policy_scoring` | Service key in `services.yaml` used for reward scoring. |
| `pool_multiplier` | integer, `4`, 1-100 | Oversampling factor. A value of 4 generates four times the normal candidate budget so the reward has alternatives to rank; cost rises roughly with the factor. |
| `parameters` | mapping, required | Tier 0 scoring configuration below. The orchestrator overrides `top_k` with `candidates_per_iteration`. |

### Tier 0 `parameters`

The policy scorer predicts a target-affinity surrogate from a Morgan-fingerprint
Tanimoto-weighted k-nearest-neighbor model and computes RDKit QED, SA score,
cLogP, and molecular weight. Each raw value is linearly interpolated through its
piecewise desirability curve. Values outside the curve retain the nearest endpoint
desirability. The composite is the weighted geometric mean

```text
D = exp(sum(w_i * ln(d_i)) / sum(w_i))
```

so one zero-desirability liability makes the whole composite zero.

| Field | Type, default, constraints | Meaning and scientific reason |
|---|---|---|
| `affinity_training_set` | non-empty list of `{smiles, value}`; required | Target-specific reference compounds and measured or validated predicted affinity labels. All values must use the same endpoint, units, and direction. The default curve assumes more-negative energy-like values are better. Illustrative labels must be replaced. |
| `affinity_k` | integer, `5`, 1-100 | Number of nearest chemical neighbors used by the local QSAR surrogate. Small values are local/noisy; large values smooth across more distant chemistry. |
| `affinity_similarity_power` | float, `2.0`, > 0 and <= 10 | Exponent on Tanimoto similarity weights. Larger values let the closest analogues dominate. Predictions far outside the training set are extrapolative regardless of this value. |
| `curves` | mapping containing exactly five named curves | Converts unlike endpoints into [0,1] desirabilities. Every curve needs at least two `{x, desirability}` points, strictly increasing `x`, finite values, and desirability from 0 to 1. |
| `weights` | mapping containing exactly the same five names; each > 0 | Relative leverage in the geometric mean. Larger affinity weight prioritizes potency; larger property weights resist potency-only collapse. |
| `min_composite_desirability` | float, `0.0`, 0-1 | Hard reward gate applied before top-k selection. Raise only after calibrating all curves, because geometric means can fall quickly. |
| `top_k` | integer or `null`, >= 1 | Service-level cap. In pipeline YAML it is overwritten with `candidates_per_iteration`; configure the latter instead. |

Each `affinity_training_set` item contains a `smiles` string and a finite numeric
`value`. Each entry under `curves` contains `points`; every point contains a
finite `x` and a `desirability` from 0 to 1.

The five required keys and default curves are:

| Key | Default points `(x, desirability)` | Scientific role |
|---|---|---|
| `target_affinity_surrogate` | `(-14,1), (-10,1), (-6,0.2), (-4,0)` | Favors target potency according to the target-specific surrogate. |
| `qed` | `(0,0), (0.35,0.25), (0.65,1), (1,1)` | Rewards a balanced drug-likeness profile rather than any single descriptor. |
| `sascore` | `(1,1), (3,1), (6,0.25), (10,0)` | Penalizes increasingly difficult structures; lower SA score is better. |
| `clogp` | `(-2,0), (1,1), (3,1), (5,0)` | Applies a soft lipophilicity window to reduce insolubility and nonspecific-binding risk without imposing a sharp cliff. |
| `molecular_weight` | `(100,0), (250,1), (450,1), (650,0)` | Applies a soft size window to balance binding opportunity against permeability and developability. |

## `pipeline` stages

Each stage is a one-key mapping. X-FORGE calls `/score` and then `/filter` on
that service and carries only passing molecules forward:

```yaml
pipeline:
  - physchem:
      require_retrosynthesis: false
  - admet_screen:
      max_candidates: 5000
  - binding:
      receptor_pdbqt: /targets/my_target/receptor.pdbqt
      receptor_pdb: /targets/my_target/receptor.pdb
      box_center: [10.0, 20.0, 30.0]
      box_size: [20.0, 20.0, 20.0]
```

The recognized built-in stage names are `synthesizability`, `physchem`,
`admet_screen`, `binding`, and `physics`. The matching URL must exist in
`config/services.yaml`.

## Tier 1: `physchem`

This is the preferred fast 2D gate. RDKit calculates descriptors and applies
Lipinski/Veber bounds, PAINS A/B/C and Brenk catalogs, warhead checks, a basic-pKa
gate, and a rapid route-feasibility heuristic.

### Descriptor and liability options

| Field | Type, default | Pass condition and why it matters |
|---|---|---|
| `max_molecular_weight` | float, `500.0` Da | MW <= threshold. Large molecules often pay permeability, solubility, and synthesis penalties. |
| `max_clogp` | float, `5.0` | RDKit cLogP <= threshold. High lipophilicity often increases insolubility, clearance liabilities, and promiscuity. |
| `max_hbond_donors` | integer, `5` | HBD <= threshold. One component of Lipinski Ro5 and passive permeability burden. |
| `max_hbond_acceptors` | integer, `10` | HBA <= threshold. Another Ro5 polarity constraint. |
| `max_tpsa` | float, `140.0` A^2 | TPSA <= threshold. Veber-style polarity boundary associated with oral exposure. |
| `max_rotatable_bonds` | integer, `10` | Rotatable bonds <= threshold. Veber flexibility boundary; excessive flexibility raises entropy and conformational uncertainty. |
| `min_formal_charge` | integer, `-1` | Inclusive lower bound on whole-molecule formal charge. |
| `max_formal_charge` | integer, `1` | Inclusive upper bound. Extreme permanent charge can impair passive permeability and complicate formulation. |
| `min_heavy_atoms` | integer, `5` | Inclusive lower size bound, useful for removing fragments too small to carry meaningful interactions. |
| `max_heavy_atoms` | integer, `70` | Inclusive upper size/complexity bound. |
| `allow_covalent_warheads` | boolean, `false` | If false, built-in and additional reactive SMARTS reject a molecule. Set true only for an explicitly covalent project with reactivity/selectivity controls. PAINS and Brenk checks still apply. |
| `additional_warhead_smarts` | list of SMARTS, empty | Project-specific reactive motifs to flag in addition to built-ins such as acyl/sulfonyl halides, isocyanates, epoxides, aziridines, Michael acceptors, and aldehydes. |

Any PAINS A/B/C or Brenk catalog match is rejected. These alerts are triage flags,
not proof of assay interference or toxicity; inspect rejected chemistry when a
known target mechanism legitimately requires a flagged motif.

### Basic-pKa options

| Field | Type, default | Meaning |
|---|---|---|
| `predicted_basic_pka_field` | string, `predicted_basic_pka` | Numeric evidence field to read from the molecule record. X-FORGE does not calculate pKa in this stage. |
| `min_basic_pka` | float or `null`, `null` | Optional inclusive lower bound for the supplied basic pKa. |
| `max_basic_pka` | float or `null`, `10.5` | Optional inclusive upper bound. Very strong bases may be persistently protonated and permeability-limited. |
| `require_pka_prediction` | boolean, `false` | If true, absence of the numeric field rejects the molecule. If false, missing values are tolerated and only structural basic-site alerts are available; that is a weaker check. |

### Rapid synthesis options

| Field | Type, default | Meaning and scientific reason |
|---|---|---|
| `require_retrosynthesis` | boolean, `true` | Requires at least one configured route heuristic to pass. If true, at least one of `building_blocks_path`, `reaction_templates`, or `route_results_path` must be configured. Set false for unconstrained exploration. |
| `building_blocks_path` | string or `null`, `null` | Path to a SMILES catalog. BRICS-derived synthons must match catalog structures. This is a fast availability proxy, not a full retrosynthesis. |
| `reaction_templates` | list of reaction SMARTS, empty | Standard transformations whose product side may match a candidate. This tests template plausibility, not selectivity, conditions, yield, or route completeness. |
| `route_results_path` | string or `null`, `null` | External route JSON keyed by molecule ID or SMILES, with `route_confidence`, `route_steps`, and optional `shared_intermediate_id`. Use this for ASKCOS/AiZynthFinder evidence. |
| `min_route_confidence` | float, `0.5`, 0-1 | Inclusive minimum external route confidence. Calibration is engine- and dataset-specific. |
| `max_route_steps` | integer, `6`, >= 1 | Inclusive maximum predicted route length. Shorter routes usually reduce cost and failure opportunities but should not override route quality. |

When several route sources are configured, passing any one is sufficient.

## Legacy `synthesizability` stage

This optional lightweight stage combines RA-Score (higher is easier) with a
normalized SA score (lower raw SA is easier). A generalized power mean with
`p = -2` emphasizes the weaker component; a sigmoid then converts it to an
activation used as a hard gate. Use `physchem` route evidence when you need
building-block or reaction-template logic.

| Field | Type, default, constraints | Meaning |
|---|---|---|
| `power` | literal `-2` | Fixed negative-order generalized mean; cannot be changed. |
| `rascore_weight` | float, `1.0`, > 0 | Relative weight of retrosynthetic accessibility classifier output. |
| `sascore_weight` | float, `1.0`, > 0 | Relative weight of normalized structural complexity. |
| `sascore_best` | float, `1.0`, >= 0 | Raw SA score mapped to easiest/1.0. |
| `sascore_worst` | float, `10.0`, > `sascore_best` | Raw SA score mapped to hardest/0.0. |
| `gate_midpoint` | float, `0.5`, 0-1 | Power-mean value mapped to sigmoid activation 0.5. |
| `gate_steepness` | float, `12.0`, > 0 and <= 100 | Sharpness of the sigmoid. High values approximate a hard cliff; low values preserve gradation. |
| `min_activation` | float, `0.5`, 0-1 | Inclusive minimum activation required to pass. |

## Tier 2: `admet_screen`

This stage uses ADMET-AI predictions, unless a prior score record supplies the
configured evidence key. Column fields therefore identify model-native endpoint
names; threshold units must match the chosen endpoint. Every enabled endpoint
must be present and finite.

### Solubility and metabolism

| Field | Type, default | Gate and interpretation |
|---|---|---|
| `solubility_column` | string, `Solubility_AqSolDB` | Source endpoint for aqueous LogS. |
| `min_log_s` | float, `-4.0` | Requires LogS > threshold. Solubility below this range commonly limits exposure and assay reliability. |
| `microsomal_clearance_column` | string or `null`, `Clearance_Microsome_AZ` | Microsomal intrinsic-clearance source; null disables reading it. |
| `max_microsomal_clint` | float or `null`, `null` | Optional CLint <= gate. Lower intrinsic clearance generally supports longer exposure. |
| `hepatocyte_clearance_column` | string or `null`, `Clearance_Hepatocyte_AZ` | Hepatocyte intrinsic-clearance source. |
| `max_hepatocyte_clint` | float or `null`, `null` | Optional hepatocyte CLint <= gate. |
| `half_life_column` | string or `null`, `Half_Life_Obach` | Metabolic half-life source. |
| `min_half_life` | float or `null`, `null` | Optional half-life >= gate. |

If multiple metabolic thresholds are enabled, the current transition gate passes
when **any one** of them passes. This is intentionally permissive for mixed
evidence; use one calibrated endpoint if all assays are not commensurate.

### Permeability, efflux, and safety

| Field | Type, default | Gate and interpretation |
|---|---|---|
| `caco2_log_papp_column` | string or `null`, `Caco2_Wang` | Caco-2 permeability source. Current ADMET-AI predictions are log10(Papp in cm/s), so -6 corresponds to `10^-6 cm/s`. |
| `mdck_log_papp_column` | string or `null`, `null` | Optional MDCK permeability source. At least Caco-2 or MDCK must be enabled. |
| `min_log_papp` | float, `0.0` | Requires the best enabled permeability > threshold. For `Caco2_Wang`, configure `-6.0` to represent Papp > `10^-6 cm/s`; the service default of 0.0 is intentionally documented but is not a practical cutoff for this model's raw output scale. |
| `pgp_efflux_ratio_column` | string or `null`, `null` | Direct efflux-ratio source. If present, it takes precedence over probability. |
| `max_pgp_efflux_ratio` | float, `2.5` | Requires direct efflux ratio < threshold. High efflux can suppress intracellular/brain exposure. |
| `pgp_risk_column` | string or `null`, `Pgp_Broccatelli` | Probability fallback when no direct ratio is configured. This model endpoint is risk, not a measured efflux ratio. |
| `max_pgp_risk` | float, `0.5` | Requires P-gp risk probability <= threshold. |
| `herg_pic50_column` | string or `null`, `null` | Direct hERG pIC50 source; takes precedence over probability. |
| `max_herg_pic50` | float, `5.0` | Requires pIC50 < threshold, corresponding to IC50 > 10 uM at the default value. Lower inhibition potency is safer. |
| `herg_risk_column` | string or `null`, `hERG` | hERG-blocking probability fallback. |
| `max_herg_risk` | float, `0.5` | Requires risk probability <= threshold. |
| `cyp_risk_columns` | mapping; defaults `cyp3a4: CYP3A4_Veith`, `cyp2d6: CYP2D6_Veith`, `cyp2c9: CYP2C9_Veith` | Names the CYP inhibition-probability endpoints to enforce. Add/remove keys to define the isoforms relevant to the project. |
| `max_cyp_risk` | float, `0.5` | Every configured CYP risk must be <= threshold. CYP inhibition is a drug-drug interaction liability. |

### Transition-gate option

| Field | Type, default | Meaning |
|---|---|---|
| `max_candidates` | integer or `null`, `null`, >= 1 | After all hard gates, non-dominated sorting ranks survivors and a geometric-mean desirability breaks ties; this caps the population sent to 3D. Null retains every hard-gate survivor. |

## Tier 3: `binding`

The binding service performs low-energy conformer generation, Meeko ligand
preparation, Vina docking, ProLIF interaction profiling, internal ligand-strain
estimation, and optional off-target docking. Receptor/grid preparation and pose
validation dominate scientific reliability.

### Required target setup

| Field | Type | Meaning |
|---|---|---|
| `receptor_pdbqt` | non-empty path | Rigid, prepared receptor used by Vina. Protonation, charges, retained cofactors/waters, and atom typing must suit the protocol. |
| `receptor_pdb` | non-empty path | Matching prepared protein structure used by ProLIF for interaction fingerprints. |
| `box_center` | three finite floats, A | Docking-grid center `[x,y,z]`. Center it on the intended pocket/reference ligand. |
| `box_size` | three positive floats, A | Docking-grid dimensions. Too small truncates poses; too large dilutes search effort. |

### Search, scoring, and strain options

| Field | Type, default, constraints | Gate or meaning |
|---|---|---|
| `exhaustiveness` | integer, `4`, 1-64 | Vina search effort. Higher values improve sampling at greater roughly linear cost. |
| `num_poses` | integer, `3`, 1-20 | Maximum poses retained for evaluation. More poses improve interaction coverage and cost more. |
| `energy_range` | float, `3.0`, > 0 and <= 20 kcal/mol | Retain poses within this energy window of the best Vina pose. |
| `cpu` | integer, `1`, 1-64 | CPU threads per docking call; operational rather than scientific. |
| `random_seed` | integer, `42`, >= 0 | Reproducibility seed for docking. |
| `max_vina_score` | float, `0.0` kcal/mol | Requires best Vina score <= threshold. More-negative scores are treated as stronger predicted binding. |
| `min_ligand_efficiency` | float, `0.0` kcal/mol per heavy atom | Requires `-vina_score / heavy_atom_count` >= threshold, rewarding affinity without merely rewarding molecular size. |
| `min_lipe_proxy` | float or `null`, `null` | Optional minimum Vina-derived pKd proxy minus cLogP. It rewards potency relative to lipophilicity but is not experimental LipE. |
| `temperature_kelvin` | float, `298.15`, > 0 | Temperature used only to convert docking energy into the pKd proxy. It does not make Vina a thermodynamic free-energy calculation. |
| `conformer_count` | integer, `20`, 1-200 | Number of free-ligand conformers attempted. More conformers sample flexibility at added CPU cost. |
| `conformer_prune_rms_angstrom` | float, `0.5`, > 0 A | RMS threshold for pruning redundant conformers. Smaller values retain more near-duplicates. |
| `max_internal_strain_kcal_mol` | float, `6.0`, > 0 | Requires estimated `max(0, E_bound_pose - E_lowest_free)` <= threshold. High strain indicates an energetically forced pose; force-field strain is an approximation. |

### Interaction constraints

| Field | Type, default | Meaning |
|---|---|---|
| `critical_interactions` | list, empty | Required pocket contacts. Each entry has `residue` (for example `ARG120.A`) and a non-empty list of ProLIF `interaction_types`. Empty disables the contact gate. |
| `critical_mode` | `all` or `any`; `all` | `all` requires every specified residue/type constraint; `any` accepts at least one. Constraints can rescue mechanistic fidelity but can also reject alternative valid binding modes. |
| `interaction_types` | list of strings or `null`; `null` | Limits the ProLIF fingerprint interactions that are computed. Null uses the library defaults. It must include types referenced by critical constraints. |

### Off-target negative design

| Field | Type, default | Meaning |
|---|---|---|
| `off_targets` | list, empty | Homologous or safety off-target docking protocols. Each entry requires `name`, `receptor_pdbqt`, `receptor_pdb`, `box_center`, and positive `box_size`, with the same preparation requirements as the target. |
| `min_selectivity_gap_target_minus_offtarget` | float or `null`, `null` kcal/mol | Optional minimum for the recorded target-minus-strongest-off-target Vina gap. Be careful with sign: Vina treats more-negative energy as stronger, so a target-favored ligand normally has a **negative** `target - off-target` value. Calibrate this field explicitly rather than assuming positive is better. |

The service also records the reverse gap. The final built-in
`docking_selectivity_gap` objective currently maximizes the target-minus-off-target
field, so sign convention deserves review for any real negative-design campaign.

## Tier 4: `physics`

This is a strict adapter for externally computed FEP+, MM-GBSA, or OpenFE
alchemical results and MD summaries; it does not run those expensive engines.
Omit this stage for a low-cost workflow.

| Field | Type, default | Gate and scientific meaning |
|---|---|---|
| `results_path` | non-empty path, required | JSON evidence keyed by molecule ID or SMILES. In Docker this must be mounted into the physics container. Missing molecule evidence rejects that candidate. |
| `allowed_methods` | non-empty list of `fep_plus`, `mm_gbsa`, `openfe_alchemical` | Acceptable calculation methods. This prevents accidental mixing with an unapproved protocol. |
| `max_binding_free_energy` | float or `null`, `null` kcal/mol | Optional target binding free energy <= threshold. More-negative is treated as stronger. Compare only method/protocol-compatible values. |
| `max_ligand_rmsd_angstrom` | float, `2.0`, > 0 A | Requires ligand RMSD < threshold. Low pocket RMSD supports pose stability but is not proof of affinity. Alignment and atom selection must be consistent. |
| `min_key_contact_persistence` | float, `0.70`, 0-1 | Requires key-contact fraction > threshold. The default demands contacts in more than 70% of analyzed frames. |
| `min_residence_time_proxy` | float or `null`, `null` | Optional proxy >= threshold. Units/definition are method-specific and must be consistent across candidates. |
| `require_off_target` | boolean, `false` | If true, external off-target binding energy must be present. This makes selectivity evidence mandatory. |
| `top_k` | integer or `null`, `null`, >= 1 | Optional physics-stage cap after gates, sorted by target energy ascending, contact persistence descending, then RMSD ascending. This is separate from final `top_k_feedback`. |

Each external result needs `method`, `binding_free_energy_kcal_mol`,
`ligand_rmsd_angstrom`, and `key_contact_persistence`. Optional evidence includes
`off_target_binding_free_energy_kcal_mol`, `residence_time_proxy`,
`binding_free_energy_uncertainty_kcal_mol`, `protocol`, `engine_version`, and
`trajectory_id`.

## Final Tier 5: `admet_moo`

The final optimizer converts every active property to pymoo's minimization
convention, performs non-dominated sorting, and chooses up to `top_k_feedback`
from Pareto Front 1 only. `properties: null` activates the five defaults, not all
available properties.

| Field | Type, default | Meaning |
|---|---|---|
| `properties` | unique list of property keys or `null`; `null` | Selects the objectives in the table below. Null activates only the five properties marked Default. At least one property is required. |
| `selection` | mapping | Configures how candidates on Pareto Front 1 are ranked and optionally diversified. |

### Property objectives

| Property key | Source evidence | Goal | Built-in desirability |
|---|---|---|---|
| `bioavailability` | `Bioavailability_Ma` | maximize | Probability clipped to [0,1]. Default. |
| `aqueous_solubility` | `Solubility_AqSolDB` | maximize | Linear 0 at -6 to 1 at -2 log(mol/L). Default. |
| `cyp3a4_inhibition` | `CYP3A4_Veith` | minimize | `1 - inhibition probability`. Default. |
| `herg_blocking` | `hERG` | minimize | `1 - blocking probability`. Default. |
| `dili` | `DILI` | minimize | `1 - DILI probability`. Default. |
| `binding_free_energy` | `binding_free_energy_kcal_mol` | minimize | Linear 0 at -4 to 1 at -12 kcal/mol. Requires physics evidence. |
| `docking_affinity` | `vina_score` | minimize | Linear 0 at -4 to 1 at -12 kcal/mol. Requires binding stage evidence. |
| `selectivity_gap` | `selectivity_gap_target_minus_offtarget` | maximize | Linear 0 at -5 to 1 at 5 kcal/mol. Intended for physics evidence. Review sign convention. |
| `docking_selectivity_gap` | same target-minus-off-target field | maximize | Same ramp; requires off-target binding evidence. Review sign convention. |
| `metabolic_clearance` | `microsomal_clint` | minimize | `1 / (1 + max(0, CLint) / 50)`. Requires Tier 2 evidence with a microsomal column. |
| `herg_pic50` | `herg_pic50` | minimize | Linear 1 at pIC50 3 to 0 at pIC50 7. Requires a direct pIC50 source. |
| `synthetic_feasibility` | `route_steps`, `route_confidence` | minimize | Burden = `steps + 5 * (1 - confidence)`; desirability = `1 - burden/12`, clipped. Requires external route evidence. |

Do not activate an objective unless an upstream stage or predictor supplies its
source evidence for every candidate. For a physics-free workflow, use
`docking_affinity` rather than `binding_free_energy`; for a docking-free workflow,
use only ADMET and synthesis objectives with available inputs.

### `admet_moo.selection`

| Field | Type, default | Meaning |
|---|---|---|
| `method` | `knee_point`, `desirability`, `hypervolume_contribution`, or `nsga3`; `knee_point` | Ranks Front 1. Knee point seeks a high-tradeoff compromise; desirability uses a weighted geometric mean; hypervolume favors unique dominated-volume contribution; NSGA-III spreads choices across reference directions. |
| `weights` | property-to-positive-float mapping or `null` | Used only by `desirability`. Unspecified active properties receive weight 1; keys for inactive properties are errors. As in Tier 0, one zero desirability makes the composite zero. |
| `reference_point` | property-to-float mapping or `null` | Used only by hypervolume. Values are in **normalized objective space**, not physical units, and each must be worse/larger than every normalized Front-1 value. Missing keys default to 1.1. |
| `nsga3_reference_partitions` | integer, `4`, 1-20 | Das-Dennis reference-direction resolution. More partitions provide finer many-objective coverage but rapidly increase the number of directions and computation. |
| `diversity` | mapping | Optional structure-based portfolio diversification described below. |

### `admet_moo.selection.diversity`

| Field | Type, default | Meaning |
|---|---|---|
| `enabled` | boolean, `false` | If true, Butina-cluster Front 1 and select round-robin across clusters instead of exhausting one chemotype. It also assigns scaffold/intermediate synthesis batches. |
| `tanimoto_distance_threshold` | float, `0.4`, > 0 and <= 1 | Butina distance cutoff where distance = `1 - Tanimoto similarity`; 0.4 therefore groups fingerprints at roughly >= 0.6 similarity. |
| `morgan_radius` | integer, `2`, 1-4 | Morgan fingerprint radius. Larger radii encode broader atom environments and more scaffold context. |
| `fingerprint_bits` | integer, `2048`, 128-8192 | Fingerprint width. More bits reduce hashing collisions at added memory cost. |

When diversity is enabled, batching uses `shared_intermediate_id` from route
evidence when present, otherwise the Bemis-Murcko scaffold, otherwise `acyclic`.
This groups synthetic opportunities but does not itself optimize route scheduling.

## HTTP options

| Field | Type, default, constraints | Meaning |
|---|---|---|
| `timeout_seconds` | float, `900`, > 0 | Per-request timeout. Docking and model startup may justify a high value; a timeout does not change scientific thresholds. |
| `max_attempts` | integer, `5`, 1-20 | Total request attempts for transient failures. |
| `backoff_seconds` | float, `1`, 0-60 | Initial retry delay; retries use exponential backoff. HTTP 429, 502, 503, and 504 are retried, while other HTTP failures are surfaced immediately. |

## Choosing a practical stage set

| Goal | Suggested stages | Final objective notes |
|---|---|---|
| Cheapest exploratory loop | no listed stages, or `physchem` | Use default ADMET objectives; predictions still run in final ADMET-MOO. |
| Developability-first 2D loop | `physchem` -> `admet_screen` | Add `metabolic_clearance` only when its threshold/source is enabled and present. |
| Docking without physics | `physchem` -> `admet_screen` -> `binding` | Use `docking_affinity`; add docking selectivity only with off-targets. |
| High-fidelity selection | `physchem` -> `admet_screen` -> `binding` -> `physics` | Use `binding_free_energy` and physics selectivity only with complete external evidence. |

Examples 2 and 7 include illustrative affinity labels. Examples 8 and 9 have
unvalidated interaction/off-target choices. Example 10 rejects molecules until
its external files contain results keyed by generated molecule IDs or SMILES.
Service-specific result schemas and limitations are also documented in
`services/physchem/README.md`, `services/binding/README.md`, and
`services/physics/README.md`.
