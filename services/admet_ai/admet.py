from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, create_model

PropertyDefinition = tuple[str, str, str]

ALL_PROPS: tuple[PropertyDefinition, ...] = (
    ("molecular_weight", "Molecular Weight", "regression"),
    ("logP", "LogP", "regression"),
    ("hydrogen_bond_acceptors", "Hydrogen Bond Acceptors", "regression"),
    ("hydrogen_bond_donors", "Hydrogen Bond Donors", "regression"),
    ("Lipinski", "Lipinski Rule of 5", "regression"),
    ("QED", "Quantitative Estimate of Druglikeness", "regression"),
    ("stereo_centers", "Stereo Centers", "regression"),
    ("tpsa", "Topological Polar Surface Area", "regression"),
    ("HIA_Hou", "Human Intestinal Absorption", "classification"),
    ("Bioavailability_Ma", "Oral Bioavailability", "classification"),
    ("Solubility_AqSolDB", "Aqueous Solubility", "regression"),
    ("Lipophilicity_AstraZeneca", "Lipophilicity", "regression"),
    ("HydrationFreeEnergy_FreeSolv", "Hydration Free Energy", "regression"),
    ("Caco2_Wang", "Caco2 Permeability", "regression"),
    ("PAMPA_NCATS", "PAMPA Permeability", "classification"),
    ("Pgp_Broccatelli", "P-glycoprotein Inhibition", "classification"),
    ("BBB_Martins", "Blood-Brain Barrier Penetration", "classification"),
    ("PPBR_AZ", "Plasma Protein Binding Rate", "regression"),
    ("VDss_Lombardo", "Volume of Distribution Steady State", "regression"),
    ("Half_Life_Obach", "Half-Life", "regression"),
    ("Clearance_Hepatocyte_AZ", "Drug Clearance Hepatocyte", "regression"),
    ("Clearance_Microsome_AZ", "Drug Clearance Microsome", "regression"),
    ("CYP1A2_Veith", "CYP1A2 Inhibition", "classification"),
    ("CYP2C19_Veith", "CYP2C19 Inhibition", "classification"),
    ("CYP2C9_Veith", "CYP2C9 Inhibition", "classification"),
    ("CYP2D6_Veith", "CYP2D6 Inhibition", "classification"),
    ("CYP3A4_Veith", "CYP3A4 Inhibition", "classification"),
    ("CYP2C9_Substrate_CarbonMangels", "CYP2C9 Substrate", "classification"),
    ("CYP2D6_Substrate_CarbonMangels", "CYP2D6 Substrate", "classification"),
    ("CYP3A4_Substrate_CarbonMangels", "CYP3A4 Substrate", "classification"),
    ("hERG", "hERG Blocking", "classification"),
    ("ClinTox", "Clinical Toxicity", "classification"),
    ("AMES", "AMES Mutagenicity", "classification"),
    ("DILI", "Drug Induced Liver Injury", "classification"),
    ("Carcinogens_Lagunin", "Carcinogenicity", "classification"),
    ("LD50_Zhu", "Acute Toxicity LD50", "regression"),
    ("Skin_Reaction", "Skin Reaction", "classification"),
    ("NR-AR", "Androgen Receptor", "classification"),
    ("NR-AR-LBD", "Androgen Receptor LBD", "classification"),
    ("NR-AhR", "Aryl Hydrocarbon Receptor", "classification"),
    ("NR-Aromatase", "Aromatase", "classification"),
    ("NR-ER", "Estrogen Receptor", "classification"),
    ("NR-ER-LBD", "Estrogen Receptor LBD", "classification"),
    ("NR-PPAR-gamma", "PPAR-gamma", "classification"),
    ("SR-ARE", "ARE", "classification"),
    ("SR-ATAD5", "ATAD5", "classification"),
    ("SR-HSE", "HSE", "classification"),
    ("SR-MMP", "Mitochondrial Membrane Potential", "classification"),
    ("SR-p53", "p53", "classification"),
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


PROPERTY_NAME_MAP: dict[str, str] = {}
for _property_id, _friendly_name, _task_type in ALL_PROPS:
    for _alias in (
        _property_id,
        _property_id.lower(),
        _slug(_property_id),
        _slug(_friendly_name),
    ):
        PROPERTY_NAME_MAP[_alias] = _property_id


def make_pydantic_model() -> type[BaseModel]:
    fields = {
        property_id: (float | None, None)
        for property_id, _, _ in ALL_PROPS
    }
    return create_model("Admet_Return", **fields, __base__=BaseModel)


Admet_Return = make_pydantic_model()


class ADMETModelError(RuntimeError):
    pass


class Admet:
    """Thread-confined adapter around one ADMET-AI v2 model instance."""

    def __init__(self, *, num_workers: int = 0, model: Any | None = None) -> None:
        if model is None:
            from admet_ai import ADMETModel

            model = ADMETModel(
                include_physchem=True,
                drugbank_path=None,
                num_workers=num_workers,
            )
        self.model = model
        self.preds: dict[str, float] = {}

    def predict_many(self, smiles: list[str]) -> list[dict[str, float]]:
        try:
            output = self.model.predict(smiles=smiles)
        except Exception as exc:
            raise ADMETModelError(f"ADMET-AI prediction failed: {exc}") from exc

        if isinstance(output, dict):
            records = [output]
        elif hasattr(output, "to_dict"):
            records = output.to_dict(orient="records")
        else:
            raise ADMETModelError(
                f"unsupported ADMET-AI result type: {type(output).__name__}"
            )
        if len(records) != len(smiles):
            raise ADMETModelError(
                "ADMET-AI discarded one or more invalid SMILES"
            )
        try:
            return [
                {
                    str(key): float(value)
                    for key, value in record.items()
                    if value is not None
                }
                for record in records
            ]
        except (TypeError, ValueError) as exc:
            raise ADMETModelError(
                "ADMET-AI returned a non-numeric prediction"
            ) from exc

    def run(self, smi: str) -> None:
        self.preds = self.predict_many([smi])[0]

    def __getattr__(self, name: str) -> Any:
        if name.startswith("get_"):
            requested = name[4:]
            property_id = (
                PROPERTY_NAME_MAP.get(requested)
                or PROPERTY_NAME_MAP.get(requested.lower())
                or PROPERTY_NAME_MAP.get(_slug(requested))
            )
            if property_id is not None and property_id in self.preds:
                return lambda selected=property_id: self.preds[selected]
        raise AttributeError(name)

    def as_obj(self) -> BaseModel:
        return Admet_Return(**self.preds)
