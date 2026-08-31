# PDE5 docking target

This target is derived from [RCSB PDB 1TBF](https://www.rcsb.org/structure/1TBF),
the 1.30 Å crystal structure of the engineered catalytic domain of human PDE5A
in complex with sildenafil (chemical component `VIA`).

`1tbf_chain_a_protein.pdb` contains chain A's standard amino-acid `ATOM`
records, with the crystallographic sildenafil, glycerol, waters, zinc, and
magnesium removed. Meeko selected alternate location A and produced
`1tbf_chain_a_prepared.pdb` for ProLIF plus
`1tbf_chain_a_receptor.pdbqt` for rigid Vina docking.

The 24 Å cubic docking box is centered at `(28.792, 30.186, 64.179)` Å, the
centroid of the 33 crystallographic sildenafil heavy atoms. The generated box
files make that choice inspectable.

The configured seed is RCSB's OpenEye canonical SMILES for `VIA`. It is
chemically equivalent to the CACTVS canonical form but avoids the latter's
bracketed `[S]` token, which is outside this REINVENT Mol2Mol prior's
vocabulary.

This is a deterministic portfolio-test target, not a validated PDE5 docking
protocol. In particular, omitting the catalytic metal ions and ordered waters
is a simplifying assumption that can change pose energetics and interactions.
