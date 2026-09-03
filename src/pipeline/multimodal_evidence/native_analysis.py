from __future__ import annotations

import json
import math
import warnings
import wave
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .contract import ValidatedMultimodalRecord, finite_json_number


MAX_IMAGE_PIXELS = 40_000_000
MAX_TABLE_ROWS = 100_000
MAX_SIGNAL_VALUES = 1_000_000
MAX_AUDIO_FRAMES = 500_000
MAX_VIDEO_METADATA_ITEMS = 32
MAX_POINT_CLOUD_POINTS = 200_000
MAX_TRAJECTORY_POINTS = 250_000


class NativeAnalysisError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _dependency_error(package: str) -> NativeAnalysisError:
    return NativeAnalysisError(
        "dependency_unavailable",
        "Local "
        f"{package} analysis requires optional multimodal capabilities. Install them with: "
        "uv sync --group multimodal",
    )


def _require_pandas() -> Any:
    try:
        import pandas as pd
    except ImportError as exc:
        raise _dependency_error("table") from exc
    return pd


def _sample_array(values: np.ndarray, limit: int) -> tuple[np.ndarray, bool]:
    flat = np.asarray(values).reshape(-1)
    if flat.size <= limit:
        return np.asarray(flat, dtype=np.float64), False
    indices = np.linspace(0, flat.size - 1, num=limit, dtype=np.int64)
    return np.asarray(flat[indices], dtype=np.float64), True


def _number(value: Any) -> float | None:
    return finite_json_number(value)


def _numeric_summary(values: np.ndarray) -> dict[str, Any]:
    values = np.asarray(values, dtype=np.float64).reshape(-1)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise NativeAnalysisError("no_numeric_values", "The selected record has no finite numeric values.")
    metrics: dict[str, Any] = {
        "finite_value_count": int(finite.size),
        "non_finite_value_count": int(values.size - finite.size),
        "mean": _number(np.mean(finite)),
        "standard_deviation": _number(np.std(finite)),
        "minimum": _number(np.min(finite)),
        "maximum": _number(np.max(finite)),
    }
    if finite.size >= 2:
        positions = np.arange(finite.size, dtype=np.float64)
        denominator = float(np.dot(positions - positions.mean(), positions - positions.mean()))
        if denominator:
            metrics["linear_trend_per_sample"] = _number(
                np.dot(positions - positions.mean(), finite - finite.mean()) / denominator
            )
    if finite.size >= 8:
        spectrum_values, sampled = _sample_array(finite, 16_384)
        spectrum = np.abs(np.fft.rfft(spectrum_values - np.mean(spectrum_values)))
        if spectrum.size > 1:
            metrics["dominant_frequency_bin"] = int(np.argmax(spectrum[1:]) + 1)
            metrics["frequency_analysis_sampled"] = sampled
    return metrics


def _analyze_image(path: Path) -> tuple[dict[str, Any], list[str]]:
    try:
        from PIL import Image, ImageStat
    except ImportError as exc:
        raise _dependency_error("image") from exc
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path) as image:
            width, height = image.size
            pixel_count = width * height
            if pixel_count > MAX_IMAGE_PIXELS:
                raise NativeAnalysisError(
                    "image_pixel_limit",
                    "The selected image exceeds the local pixel safety limit.",
                )
            image.load()
            statistics = ImageStat.Stat(image)
            bands = list(image.getbands())
            means = {
                bands[index]: _number(value)
                for index, value in enumerate(statistics.mean)
                if index < len(bands)
            }
            extrema = {
                bands[index]: [
                    _number(statistics.extrema[index][0]),
                    _number(statistics.extrema[index][1]),
                ]
                for index in range(min(len(bands), len(statistics.extrema)))
            }
            return (
                {
                    "width": int(width),
                    "height": int(height),
                    "pixel_count": int(pixel_count),
                    "mode": str(image.mode),
                    "channel_count": len(bands),
                    "channel_means": means,
                    "channel_extrema": extrema,
                },
                ["Only structural and aggregate pixel statistics were computed locally."],
            )


def _read_table(path: Path) -> Any:
    pd = _require_pandas()
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, nrows=MAX_TABLE_ROWS)
    if suffix == ".tsv":
        return pd.read_csv(path, sep="\t", nrows=MAX_TABLE_ROWS)
    if suffix in {".xls", ".xlsx"}:
        return pd.read_excel(path, nrows=MAX_TABLE_ROWS)
    if suffix == ".parquet":
        return pd.read_parquet(path).head(MAX_TABLE_ROWS)
    raise NativeAnalysisError("unsupported_format", "The selected table format is not supported locally.")


def _analyze_table(path: Path) -> tuple[dict[str, Any], list[str]]:
    pd = _require_pandas()
    frame = _read_table(path)
    rows, columns = frame.shape
    dtype_counts = Counter(str(dtype) for dtype in frame.dtypes)
    cell_count = rows * columns
    missing_cells = int(frame.isna().sum().sum()) if cell_count else 0
    numeric_summary: dict[str, dict[str, float | None]] = {}
    for column in list(frame.columns)[:20]:
        series = frame[column]
        if not pd.api.types.is_numeric_dtype(series):
            continue
        numeric_values = np.asarray(series.to_numpy(dtype=np.float64, na_value=np.nan))
        finite = numeric_values[np.isfinite(numeric_values)]
        if finite.size == 0:
            continue
        numeric_summary[str(column)[:128]] = {
            "mean": _number(np.mean(finite)),
            "standard_deviation": _number(np.std(finite)),
            "minimum": _number(np.min(finite)),
            "maximum": _number(np.max(finite)),
        }
    return (
        {
            "rows_analyzed": int(rows),
            "column_count": int(columns),
            "missing_cell_fraction": _number(missing_cells / cell_count) if cell_count else 0.0,
            "dtype_counts": dict(sorted(dtype_counts.items())),
            "numeric_column_summary": numeric_summary,
            "row_limit": MAX_TABLE_ROWS,
        },
        [
            "Table analysis is limited to aggregate statistics and the first local row budget.",
            "Cell values and row-level records are not retained in the context.",
        ],
    )


def _load_signal(path: Path) -> tuple[np.ndarray, bool]:
    suffix = path.suffix.lower()
    if suffix == ".npy":
        values = np.load(path, allow_pickle=False, mmap_mode="r")
        return np.asarray(values), False
    if suffix == ".npz":
        with np.load(path, allow_pickle=False) as archive:
            if not archive.files:
                raise NativeAnalysisError("empty_signal", "The selected signal archive contains no arrays.")
            return np.asarray(archive[archive.files[0]]), False
    pd = _require_pandas()
    separator = "\t" if suffix == ".tsv" else ","
    frame = pd.read_csv(path, sep=separator, header=None, nrows=MAX_SIGNAL_VALUES)
    numeric = frame.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    return numeric, True


def _analyze_signal(path: Path) -> tuple[dict[str, Any], list[str]]:
    values, bounded_by_rows = _load_signal(path)
    sampled_values, sampled = _sample_array(values, MAX_SIGNAL_VALUES)
    metrics = _numeric_summary(sampled_values)
    metrics["source_value_count"] = int(np.asarray(values).size)
    metrics["analysis_value_count"] = int(sampled_values.size)
    metrics["analysis_sampled"] = bool(sampled or bounded_by_rows)
    return (
        metrics,
        [
            "Signal metrics are aggregate statistics; dominant frequency is a sample-bin index, not a physical frequency.",
        ],
    )


def _pcm_values(raw: bytes, sample_width: int) -> np.ndarray:
    if sample_width == 1:
        return np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0
    if sample_width == 2:
        return np.frombuffer(raw, dtype="<i2").astype(np.float64)
    if sample_width == 3:
        packed = np.frombuffer(raw, dtype=np.uint8)
        if packed.size % 3:
            raise NativeAnalysisError("invalid_audio", "The WAV payload has an invalid sample width.")
        values = packed.reshape(-1, 3).astype(np.int32)
        signed = values[:, 0] | (values[:, 1] << 8) | (values[:, 2] << 16)
        return np.where(signed & 0x800000, signed - 0x1000000, signed).astype(np.float64)
    if sample_width == 4:
        return np.frombuffer(raw, dtype="<i4").astype(np.float64)
    raise NativeAnalysisError("unsupported_audio", "Only PCM WAV sample widths from 8 to 32 bits are supported locally.")


def _analyze_audio(path: Path) -> tuple[dict[str, Any], list[str]]:
    with wave.open(str(path), "rb") as audio:
        frame_count = audio.getnframes()
        sample_rate = audio.getframerate()
        channels = audio.getnchannels()
        sample_width = audio.getsampwidth()
        read_frames = min(frame_count, MAX_AUDIO_FRAMES)
        raw = audio.readframes(read_frames)
    values = _pcm_values(raw, sample_width)
    max_amplitude = float(2 ** (8 * sample_width - 1))
    normalized = values / max_amplitude if max_amplitude else values
    return (
        {
            "frame_count": int(frame_count),
            "sample_rate_hz": int(sample_rate),
            "channel_count": int(channels),
            "duration_seconds": _number(frame_count / sample_rate) if sample_rate else None,
            "rms_amplitude": _number(math.sqrt(float(np.mean(np.square(normalized))))) if normalized.size else 0.0,
            "frames_analyzed": int(read_frames),
        },
        ["Audio analysis is limited to WAV header metadata and bounded RMS amplitude."],
    )


def _metadata_value(value: Any) -> str | int | float | bool | None:
    if isinstance(value, (str, int, bool)):
        return value
    number = _number(value)
    return number


def _analyze_video(path: Path) -> tuple[dict[str, Any], list[str]]:
    try:
        import imageio.v3 as iio
    except ImportError as exc:
        raise _dependency_error("video") from exc
    metadata = iio.immeta(path)
    properties = iio.improps(path)
    metadata_items: dict[str, str | int | float | bool | None] = {}
    if isinstance(metadata, dict):
        for key, value in list(sorted(metadata.items()))[:MAX_VIDEO_METADATA_ITEMS]:
            safe_value = _metadata_value(value)
            if safe_value is not None:
                metadata_items[str(key)[:128]] = safe_value
    shape = getattr(properties, "shape", None)
    return (
        {
            "frame_count": _metadata_value(getattr(properties, "n_images", None)),
            "frame_rate_hz": _metadata_value(metadata_items.get("fps") or metadata_items.get("framerate")),
            "frame_shape": [int(item) for item in shape] if isinstance(shape, tuple) else None,
            "metadata": metadata_items,
        },
        ["Video analysis reads bounded container metadata only; no frames are rendered or sent remotely."],
    )


def _load_point_cloud(path: Path) -> tuple[np.ndarray, int, bool]:
    suffix = path.suffix.lower()
    if suffix == ".npy":
        values = np.load(path, allow_pickle=False, mmap_mode="r")
        array = np.asarray(values)
        if array.ndim < 2 or array.shape[-1] < 3:
            raise NativeAnalysisError("invalid_point_cloud", "The selected .npy point cloud must have at least three coordinates per point.")
        flat = array.reshape(-1, array.shape[-1])
        point_count = int(flat.shape[0])
        return np.asarray(flat[:MAX_POINT_CLOUD_POINTS, :3], dtype=np.float64), point_count, point_count > MAX_POINT_CLOUD_POINTS
    if suffix == ".ply":
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            header_lines: list[str] = []
            for _ in range(512):
                line = handle.readline()
                if not line:
                    break
                header_lines.append(line.strip())
                if line.strip() == "end_header":
                    break
            if not header_lines or header_lines[-1] != "end_header" or not header_lines[0].startswith("ply"):
                raise NativeAnalysisError("invalid_point_cloud", "The selected PLY file has no supported header.")
            if not any(line == "format ascii 1.0" for line in header_lines):
                raise NativeAnalysisError("unsupported_point_cloud", "Only ASCII PLY point clouds are supported locally.")
            declared_count = next(
                (int(line.split()[-1]) for line in header_lines if line.startswith("element vertex ")),
                0,
            )
            points: list[list[float]] = []
            for _ in range(min(declared_count, MAX_POINT_CLOUD_POINTS)):
                row = handle.readline().split()
                if len(row) < 3:
                    continue
                points.append([float(row[0]), float(row[1]), float(row[2])])
        return np.asarray(points, dtype=np.float64), declared_count, declared_count > MAX_POINT_CLOUD_POINTS
    points: list[list[float]] = []
    point_count = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            row = line.replace(",", " ").split()
            if len(row) < 3:
                continue
            try:
                point = [float(row[0]), float(row[1]), float(row[2])]
            except ValueError:
                continue
            point_count += 1
            if len(points) < MAX_POINT_CLOUD_POINTS:
                points.append(point)
    return np.asarray(points, dtype=np.float64), point_count, point_count > MAX_POINT_CLOUD_POINTS


def _analyze_three_d(path: Path) -> tuple[dict[str, Any], list[str]]:
    points, point_count, sampled = _load_point_cloud(path)
    finite_points = points[np.all(np.isfinite(points), axis=1)] if points.size else points
    if finite_points.shape[0] < 1:
        raise NativeAnalysisError("no_points", "The selected point cloud has no finite XYZ points.")
    metrics: dict[str, Any] = {
        "point_count": int(point_count),
        "points_analyzed": int(finite_points.shape[0]),
        "bbox_min": [_number(value) for value in np.min(finite_points, axis=0)],
        "bbox_max": [_number(value) for value in np.max(finite_points, axis=0)],
        "analysis_sampled": sampled,
    }
    if finite_points.shape[0] >= 3:
        centered = finite_points - np.mean(finite_points, axis=0)
        _, singular_values, _ = np.linalg.svd(centered, full_matrices=False)
        total = float(np.sum(np.square(singular_values)))
        if total:
            metrics["pca_explained_variance_ratio"] = [
                _number(value) for value in np.square(singular_values) / total
            ]
    return (
        metrics,
        ["Point-cloud geometry is summarized locally; no mesh rendering or semantic interpretation occurs in Batch A."],
    )


def _trajectory_points_from_json(path: Path) -> tuple[np.ndarray, int, bool]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("points", payload.get("trajectory"))
    if not isinstance(payload, list):
        raise NativeAnalysisError("invalid_trajectory", "The selected trajectory JSON must contain a points array.")
    points: list[list[float]] = []
    point_count = 0
    for raw_point in payload:
        if isinstance(raw_point, dict):
            candidates = [raw_point.get(key) for key in ("x", "y", "z")]
        elif isinstance(raw_point, (list, tuple)):
            candidates = list(raw_point[:3])
        else:
            continue
        if len(candidates) < 2:
            continue
        try:
            point = [float(value) for value in candidates if value is not None]
        except (TypeError, ValueError):
            continue
        if len(point) < 2:
            continue
        point_count += 1
        if len(points) < MAX_TRAJECTORY_POINTS:
            points.append(point)
    return np.asarray(points, dtype=np.float64), point_count, point_count > MAX_TRAJECTORY_POINTS


def _trajectory_points_from_table(path: Path) -> tuple[np.ndarray, int, bool]:
    pd = _require_pandas()
    separator = "\t" if path.suffix.lower() == ".tsv" else ","
    frame = pd.read_csv(path, sep=separator, nrows=MAX_TRAJECTORY_POINTS)
    numeric = frame.apply(pd.to_numeric, errors="coerce").select_dtypes(include=["number"])
    if numeric.shape[1] < 2:
        raise NativeAnalysisError("invalid_trajectory", "The selected trajectory table needs at least two numeric coordinates.")
    values = np.asarray(numeric.iloc[:, :3].to_numpy(dtype=np.float64))
    return values, int(values.shape[0]), True


def _analyze_trajectory(path: Path) -> tuple[dict[str, Any], list[str]]:
    if path.suffix.lower() == ".json":
        points, point_count, sampled = _trajectory_points_from_json(path)
    else:
        points, point_count, sampled = _trajectory_points_from_table(path)
    finite_points = points[np.all(np.isfinite(points), axis=1)] if points.size else points
    if finite_points.shape[0] < 2:
        raise NativeAnalysisError("no_trajectory_points", "The selected trajectory has fewer than two finite points.")
    step_lengths = np.linalg.norm(np.diff(finite_points, axis=0), axis=1)
    return (
        {
            "point_count": int(point_count),
            "points_analyzed": int(finite_points.shape[0]),
            "path_length": _number(np.sum(step_lengths)),
            "mean_step_length": _number(np.mean(step_lengths)),
            "maximum_step_length": _number(np.max(step_lengths)),
            "analysis_sampled": sampled,
        },
        ["Trajectory speed is represented as per-sample displacement because no time-unit contract is available."],
    )


def _analyze_text_like(path: Path) -> tuple[dict[str, Any], list[str]]:
    line_count = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65_536), b""):
            line_count += block.count(b"\n")
    return (
        {"byte_count": int(path.stat().st_size), "line_count": int(line_count)},
        ["Only file-size and line-count metadata were computed for this modality."],
    )


def _analyze_molecule(_: Path) -> tuple[dict[str, Any], list[str]]:
    raise NativeAnalysisError(
        "unsupported_modality",
        "Molecule records are not supported in Batch A because RDKit is not a declared dependency.",
    )


_ANALYZERS: dict[str, Callable[[Path], tuple[dict[str, Any], list[str]]]] = {
    "image": _analyze_image,
    "table": _analyze_table,
    "signal": _analyze_signal,
    "audio": _analyze_audio,
    "video": _analyze_video,
    "threeD": _analyze_three_d,
    "trajectory": _analyze_trajectory,
    "text": _analyze_text_like,
    "symbolic": _analyze_text_like,
    "molecule": _analyze_molecule,
}


def analyze_record(record: ValidatedMultimodalRecord) -> dict[str, Any]:
    analyzer = _ANALYZERS[record.modality]
    try:
        metrics, limitations = analyzer(record.source_path)
    except NativeAnalysisError:
        raise
    except Exception as exc:
        raise NativeAnalysisError(
            "analysis_failed",
            "Local native analysis could not parse the selected record.",
        ) from exc
    return {
        "record_id": record.record_id,
        "modality": record.modality,
        "status": "success",
        "metrics": metrics,
        "limitations": limitations,
    }
