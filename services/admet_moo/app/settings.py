from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    models_dir: Path | None = None
    num_workers: int = 0

    @classmethod
    def from_env(cls) -> Settings:
        models_dir = os.getenv("ADMET_MODELS_DIR")
        return cls(
            models_dir=Path(models_dir) if models_dir else None,
            num_workers=int(os.getenv("ADMET_NUM_WORKERS", "0")),
        )
