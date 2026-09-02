from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


AUTOGEN_RUN_CONFIG_VERSION = "effective_autogen_run_config_v1"


@dataclass(frozen=True)
class EffectiveAutoGenRunConfig:
    schema_version: str
    providers: tuple[str, ...]
    use_llm: bool
    max_subhypotheses: int
    max_round: int
    speaker_selection_method: str
    human_input_mode: str
    use_native_autogen: bool
    restart_from_decomposition: bool

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["providers"] = list(self.providers)
        return payload


def resolve_effective_autogen_run_config(
    *,
    providers: Iterable[str],
    use_llm: bool = True,
    restart_from_decomposition: bool = False,
) -> EffectiveAutoGenRunConfig:
    normalized_providers = tuple(dict.fromkeys(
        str(provider or "").strip().lower().replace("-", "_")
        for provider in providers
        if str(provider or "").strip()
    ))
    if not normalized_providers:
        raise ValueError("The canonical literature-provider resolver returned no live providers")
    return EffectiveAutoGenRunConfig(
        schema_version=AUTOGEN_RUN_CONFIG_VERSION,
        providers=normalized_providers,
        use_llm=bool(use_llm),
        max_subhypotheses=6,
        max_round=12,
        speaker_selection_method="round_robin",
        human_input_mode="NEVER",
        use_native_autogen=False,
        restart_from_decomposition=bool(restart_from_decomposition),
    )
