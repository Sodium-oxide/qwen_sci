#!/usr/bin/env bash
set -euo pipefail

prepare_only=false
until_stage=author
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prepare-only)
      prepare_only=true
      shift
      ;;
    --until)
      if [[ $# -lt 2 ]]; then
        printf '%s\n' '--until requires survey, idea, exp_design, or author.' >&2
        exit 2
      fi
      case "$2" in
        survey|idea|exp_design|author) until_stage="$2" ;;
        *) printf 'Invalid stage: %s\n' "$2" >&2; exit 2 ;;
      esac
      shift 2
      ;;
    *)
      printf 'Usage: bash scripts/run_mpa_fresh.sh [--prepare-only] [--until survey|idea|exp_design|author]\n' >&2
      exit 2
      ;;
  esac
done

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$repo_root"
run_id="maleimide-polyacetylene-fresh-$(date +%Y%m%d-%H%M%S)-${RANDOM}"
config_path="$repo_root/workspace/fresh-configs/${run_id}.yaml"
cache_root="$repo_root/workspace/fresh-cache/${run_id}"

uv run python - "$config_path" "$cache_root" <<'PY'
import sys
from pathlib import Path

from omegaconf import OmegaConf

from src.config import load_config

config_path = Path(sys.argv[1])
cache_root = Path(sys.argv[2])
data = OmegaConf.to_container(OmegaConf.load("src/config/default.yaml"), resolve=False)


def disable_caches(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key.endswith("cache_enabled"):
                node[key] = False
            elif key in {"cache", "section_cache", "checkpoint"} and isinstance(value, dict):
                value["enabled"] = False
                if "mode" in value:
                    value["mode"] = "disabled"
                disable_caches(value)
            else:
                disable_caches(value)
    elif isinstance(node, list):
        for value in node:
            disable_caches(value)


disable_caches(data)
config = OmegaConf.create(data)
overrides = {
    "survey.BasicInfo.cache_path": str(cache_root / "survey"),
    "survey.BasicInfo.skip_exist": False,
    "survey.ModuleInfo.WorkCollector.min_seed_papers_per_sh": 2,
    "survey.ModuleInfo.WorkAnalyzer.cluster_cache_enabled": False,
    "survey.ModuleInfo.WorkAnalyzer.relation_graph_cache_enabled": False,
    "idea.run.rag_config": str(config_path),
    "idea.mcts.enable_vector_memory": False,
    "idea.mcts.enable_symbolic_memory": False,
    "idea.mcts.symbolic_memory_path": str(cache_root / "idea" / "symbolic_memory"),
    "experiment_design.formal_reasoning.definition_retrieval.checkpoint.root":
        str(cache_root / "experiment_design" / "definitions"),
    "experiment_design.retrieval.cache.root":
        str(cache_root / "experiment_design" / "results"),
    "experiment_design.retrieval.fulltext.cache_dir":
        str(cache_root / "experiment_design" / "fulltext"),
    "research_plan_author.authoring.section_cache.root": str(cache_root / "author"),
}
for key, value in overrides.items():
    OmegaConf.update(config, key, value, merge=False)

config_path.parent.mkdir(parents=True, exist_ok=True)
OmegaConf.save(config, config_path, resolve=False)
resolved = load_config(str(config_path))
OmegaConf.to_container(resolved, resolve=True)
print(f"Fresh-run config: {config_path}")
print(f"Isolated cache directory: {cache_root}")
PY

printf '\nNew run: %s\nOutput: %s/workspace/science-runs/%s\n\n' \
  "$run_id" "$repo_root" "$run_id"

if [[ "$prepare_only" == true ]]; then
  printf 'Configuration validated; research workflow was not started.\n'
  exit 0
fi

topic=$(cat <<'TOPIC'
The development of stable, high-conductivity n-type conjugated polymers is crucial for advancing organic electronics but lags behind p-type materials. Polyacetylene analogues are attractive targets, but incorporating electron-withdrawing groups to achieve low LUMO energies often disrupts backbone planarity essential for conductivity. Novel synthetic strategies are needed to create well-defined, planar, electron-deficient conjugated polymers.

Maleimide Polyacetylene (mPA), featuring an alternating vinylene (-CH=CH-) unit and N-alkylated maleimide unit backbone, is synthesized via a two-stage strategy:
1. ROMP: A N-alkylated maleimide-fused cyclobutene monomer (M) is polymerized using a Mo-based Schrock catalyst to yield a soluble, non-conjugated precursor polymer (P) containing alternating vinylene and N-alkylated dihydro-maleimide units.
2. Oxidation: The precursor P is converted to the fully conjugated mPA using triethylamine (TEA) and a mild oxidant (e.g., TCNQ or I₂).

Provide a comprehensive chemical analysis of this system, addressing:
a) The strategic rationale for employing the two-stage precursor ROMP approach and the specific catalyst choice.
b) The complete mechanistic basis for the conversion of the precursor polymer P to mPA under the notably mild TEA/oxidant conditions.
c) The key structure-property relationships in mPA that determine its electronic characteristics (LUMO level, n-type behavior) and potential for electrical conductivity (backbone planarity).
d) The overall significance of this approach for developing n-type conjugated polymers.

TOPIC
)

uv run qwensci science \
  --config "$config_path" \
  --topic "$topic" \
  --discipline-id "Chemistry" \
  --discipline-id "Materials Science" \
  --run-id "$run_id" \
  --output-root "$repo_root/workspace/science-runs" \
  --quantitative-mode off \
  --until "$until_stage"
