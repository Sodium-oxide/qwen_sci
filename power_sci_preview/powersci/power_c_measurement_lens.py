"""Deterministic measurement lenses with provenance-preserving metadata."""
from __future__ import annotations
from dataclasses import dataclass, field
import math
import random
from typing import Any, Dict, Mapping, Optional
from .power_c_case_registry import CaseManifest, TruthDataset, _hash


@dataclass(frozen=True)
class LensSpec:
    lens_id: str
    name: str
    version: str = "1.0.0"
    sample_rate_hz: float = 100.0
    noise_std: float = 0.0
    noise_unit: str = "native"
    seed: int = 0
    transformations: tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    preserve_units: bool = True
    preserve_coordinates: bool = True
    schema_version: str = "lens_spec_v2"

    def __post_init__(self) -> None:
        indexes = [int(x.get("index", -1)) for x in self.transformations]
        if indexes != list(range(len(indexes))):
            raise ValueError("lens transformation indexes must be contiguous from zero")
        if self.noise_std < 0 or self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive and noise_std non-negative")

    @property
    def content_hash(self) -> str: return _hash(self.to_dict(include_hash=False))

    def to_dict(self, include_hash: bool = True) -> Dict[str, Any]:
        d = {"schema_version": self.schema_version, "lens_id": self.lens_id, "name": self.name,
             "version": self.version, "sample_rate_hz": self.sample_rate_hz, "noise_std": self.noise_std,
             "noise_unit": self.noise_unit, "seed": self.seed, "transformations": list(self.transformations),
             "preserve_units": self.preserve_units, "preserve_coordinates": self.preserve_coordinates}
        if include_hash: d["content_hash"] = self.content_hash
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LensSpec":
        values = dict(data)
        values.pop("content_hash", None)
        values["transformations"] = tuple(values.get("transformations", ()))
        return cls(**values)


LensSpecV2 = LensSpec


@dataclass
class LensResult:
    case_id: str
    lens_id: str
    time_s: list[float]
    values: Dict[str, list[float]]
    variable_metadata: Dict[str, Dict[str, Any]]
    provenance: Dict[str, Any]

    @property
    def content_hash(self) -> str: return _hash(self.to_dict(include_hash=False))

    def to_dict(self, include_hash: bool = True) -> Dict[str, Any]:
        d = {"case_id": self.case_id, "lens_id": self.lens_id, "time_s": self.time_s,
             "values": self.values, "variable_metadata": self.variable_metadata, "provenance": self.provenance}
        if include_hash: d["content_hash"] = self.content_hash
        return d


def high_quality_lens() -> LensSpec:
    return LensSpec("lens_high_quality", "high_quality_simulation", sample_rate_hz=100.0,
        transformations=({"index": 0, "type": "identity"},))


def pmu_lens() -> LensSpec:
    return LensSpec("lens_pmu_equivalent", "pmu_equivalent_sampling", sample_rate_hz=50.0,
        transformations=({"index": 0, "type": "resample", "method": "nearest"},
                         {"index": 1, "type": "phasor_quantization", "bits": 16},))


def noisy_low_rate_lens(seed: int = 1729) -> LensSpec:
    return LensSpec("lens_low_rate_noisy", "low_sampling_high_noise", sample_rate_hz=10.0,
        noise_std=0.01, noise_unit="native", seed=seed,
        transformations=({"index": 0, "type": "resample", "method": "linear"},
                         {"index": 1, "type": "additive_gaussian_noise"},))


def apply_lens(dataset: TruthDataset, case: CaseManifest, spec: LensSpec) -> LensResult:
    if dataset.case_id != case.case_id: raise ValueError("dataset and case_id do not match")
    if spec.sample_rate_hz > 100.0:
        raise ValueError("sample_rate_hz cannot exceed source 100 Hz")
    stride = max(1, int(round(100.0 / spec.sample_rate_hz)))
    indexes = list(range(0, len(dataset.time_s), stride))
    if indexes[-1] != len(dataset.time_s) - 1: indexes.append(len(dataset.time_s) - 1)
    times = [dataset.time_s[i] for i in indexes]
    rng = random.Random(spec.seed)
    values: Dict[str, list[float]] = {}
    for name, series in dataset.values.items():
        out = [float(series[i]) for i in indexes]
        if spec.lens_id == "lens_pmu_equivalent":
            out = [round(x, 5) for x in out]
        if spec.noise_std:
            out = [x + rng.gauss(0.0, spec.noise_std) for x in out]
        values[name] = out
    metadata = {name: dict(meta, sampling_rate_hz=spec.sample_rate_hz,
                           source_variable=name, lens_id=spec.lens_id,
                           noise_std=spec.noise_std, noise_unit=spec.noise_unit,
                           seed=spec.seed, normalized=False)
                for name, meta in dataset.variable_metadata.items()}
    provenance = {"source_dataset_hash": dataset.content_hash, "case_manifest_hash": case.content_hash,
                  "lens_spec_hash": spec.content_hash, "transformations": list(spec.transformations),
                  "seed": spec.seed, "sample_rate_hz": spec.sample_rate_hz}
    return LensResult(case.case_id, spec.lens_id, times, values, metadata, provenance)
