from __future__ import annotations

from functools import lru_cache

from rdkit import Chem
from rdkit.Chem.Draw import rdMolDraw2D


class MoleculeDepictionError(ValueError):
    pass


@lru_cache(maxsize=2_048)
def render_molecule_svg(smiles: str, width: int = 360, height: int = 240) -> str:
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        raise MoleculeDepictionError("RDKit could not parse the molecule SMILES")

    drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
    options = drawer.drawOptions()
    options.addStereoAnnotation = True
    options.bondLineWidth = 1.7
    options.padding = 0.08
    rdMolDraw2D.PrepareAndDrawMolecule(drawer, molecule)
    drawer.FinishDrawing()
    return drawer.GetDrawingText()
