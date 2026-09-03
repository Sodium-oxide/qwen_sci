from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List


@dataclass
class AndesRunResult:
    ok: bool
    message: str
    data: Dict[str, Any] = field(default_factory=dict)


class AndesAdapter:
    def __init__(self) -> None:
        try:
            import andes  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on optional install
            self.andes = None
            self.import_error = exc
        else:
            self.andes = andes
            self.import_error = None
        self.system = None

    @property
    def available(self) -> bool:
        return self.andes is not None

    def initialize(self, case_path: str | Path, *, setup: bool = True) -> AndesRunResult:
        if not self.available:
            return AndesRunResult(False, f'ANDES is not available: {self.import_error}')
        path = Path(case_path)
        if not path.exists():
            return AndesRunResult(False, f'Case file does not exist: {path}')
        try:
            self.system = self.andes.load(str(path), setup=setup)
        except Exception as exc:
            return AndesRunResult(False, f'ANDES initialize failed: {exc}')
        return AndesRunResult(True, 'ANDES system initialized')

    def run(self, routine: str = 'TDS', **kwargs: Any) -> AndesRunResult:
        if self.system is None:
            return AndesRunResult(False, 'ANDES system is not initialized')
        try:
            runner = getattr(self.system, routine)
            runner.config.update(kwargs)
            runner.run()
        except Exception as exc:
            return AndesRunResult(False, f'ANDES run failed: {exc}')
        return AndesRunResult(True, f'ANDES {routine} finished')

    def extract(self, names: Iterable[str]) -> AndesRunResult:
        if self.system is None:
            return AndesRunResult(False, 'ANDES system is not initialized')
        data: Dict[str, Any] = {}
        for name in names:
            try:
                data[name] = getattr(self.system, name)
            except Exception as exc:
                data[name] = {'error': str(exc)}
        return AndesRunResult(True, 'ANDES data extracted', data)
