from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    reinvent_executable: str = "reinvent"
    model_path: Path = Path("/models/mol2mol_medium_similarity.prior")
    device: str = "cpu"
    timeout_seconds: int = 900

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            reinvent_executable=os.getenv("REINVENT_EXECUTABLE", "reinvent"),
            model_path=Path(
                os.getenv(
                    "REINVENT_MODEL_PATH",
                    "/models/mol2mol_medium_similarity.prior",
                )
            ),
            device=os.getenv("REINVENT_DEVICE", "cpu"),
            timeout_seconds=int(os.getenv("REINVENT_TIMEOUT_SECONDS", "900")),
        )
