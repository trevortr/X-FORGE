from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import Any

from .settings import Settings


class ADMETPredictionError(RuntimeError):
    pass


class InvalidMoleculeError(ADMETPredictionError):
    pass


@dataclass(frozen=True)
class PredictorReadiness:
    available: bool
    model_loaded: bool
    device: str | None = None
    detail: str | None = None


class ADMETAIPredictor:
    """Lazy, thread-safe adapter around admet_ai.ADMETModel."""

    def __init__(
        self,
        settings: Settings,
        model_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.settings = settings
        self._model_factory = model_factory
        self._model: Any | None = None
        self._load_error: str | None = None
        self._lock = RLock()

    def _factory(self) -> Callable[..., Any]:
        if self._model_factory is not None:
            return self._model_factory
        from admet_ai import ADMETModel

        return ADMETModel

    def load(self) -> Any:
        with self._lock:
            if self._model is not None:
                return self._model
            kwargs: dict[str, Any] = {
                "include_physchem": False,
                "drugbank_path": None,
                "num_workers": self.settings.num_workers,
            }
            if self.settings.models_dir is not None:
                kwargs["models_dir"] = self.settings.models_dir
            try:
                self._model = self._factory()(**kwargs)
                self._load_error = None
            except Exception as exc:
                self._load_error = str(exc)
                raise ADMETPredictionError(f"could not load ADMET-AI: {exc}") from exc
            return self._model

    def readiness(self) -> PredictorReadiness:
        try:
            model = self.load()
        except ADMETPredictionError as exc:
            return PredictorReadiness(
                available=False,
                model_loaded=False,
                detail=str(exc),
            )
        return PredictorReadiness(
            available=True,
            model_loaded=True,
            device=str(getattr(model, "device", "unknown")),
        )

    def predict(self, smiles: list[str]) -> list[dict[str, float]]:
        if not smiles:
            return []
        model = self.load()
        try:
            with self._lock:
                output = model.predict(smiles=smiles)
        except Exception as exc:
            raise ADMETPredictionError(f"ADMET-AI prediction failed: {exc}") from exc

        if isinstance(output, dict):
            records = [output]
        elif hasattr(output, "to_dict"):
            records = output.to_dict(orient="records")
        else:
            raise ADMETPredictionError(
                f"ADMET-AI returned unsupported result type {type(output).__name__}"
            )

        if len(records) != len(smiles):
            raise InvalidMoleculeError(
                "ADMET-AI discarded one or more invalid SMILES; no candidates were optimized"
            )
        try:
            return [
                {str(key): float(value) for key, value in record.items()}
                for record in records
            ]
        except (TypeError, ValueError) as exc:
            raise ADMETPredictionError(
                "ADMET-AI returned a non-numeric prediction"
            ) from exc
