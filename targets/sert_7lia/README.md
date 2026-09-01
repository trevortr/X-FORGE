# Human SERT docking target

This target is derived from [RCSB PDB 7LIA](https://www.rcsb.org/structure/7LIA),
the 3.30 A cryo-EM structure of human sodium-dependent serotonin transporter
(SERT) in an outward-facing, serotonin-bound conformation.

`7lia_chain_a_protein.pdb` contains the standard amino-acid `ATOM` records for
the human SERT chain A. Meeko selected alternate location A, removed residues
with incomplete chemistry where necessary, added receptor hydrogens, and wrote
`7lia_chain_a_prepared.pdb` for ProLIF plus
`7lia_chain_a_receptor.pdbqt` for rigid Vina docking.

The 24 A cubic box is centered at `(123.384, 128.911, 137.778)` A, the
heavy-atom centroid of crystallographic serotonin `SRO A 901` in the central
substrate site. The second serotonin (`SRO A 905`) occupies the extracellular
allosteric site and was not used to define the box.

This is an integration-test protocol, not a validated production SERT docking
workflow. The preparation removes serotonin, sodium, chloride, membrane lipids,
cholesterol, antibody chains, and other non-protein components. SERT transport
and substrate recognition are ion- and conformational-state-dependent, so
omitting those components can materially change poses and scores.
