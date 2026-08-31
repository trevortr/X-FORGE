# COX-2 docking target

This target is derived from the RCSB Protein Data Bank entry
[4PH9](https://www.rcsb.org/structure/4PH9), the 1.81 Å crystal structure of
S-ibuprofen bound to murine cyclooxygenase-2.

`4ph9_chain_a_protein.pdb` contains the standard amino-acid ATOM records from
chain A, excluding the crystallographic ligand, solvent, glycans, detergents,
and heme. Meeko produced `4ph9_chain_a_prepared.pdb`, which ProLIF reads, and
the corresponding `4ph9_chain_a_receptor.pdbqt` rigid Vina receptor. Using both
prepared outputs keeps the interaction fingerprint and docking coordinates
consistent.

The docking box is centered on the crystallographic chain-A ibuprofen site at
approximately `(13.008, 23.487, 25.256)` Å. These assets are suitable for the
portfolio workflow and its integration test; they are not a validated
production docking protocol.
