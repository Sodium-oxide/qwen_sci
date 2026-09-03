from __future__ import annotations

from pprint import pprint

from .power_b_smib_examples import (
    build_smib_correct_model,
    build_smib_missing_closure_model,
    build_smib_power_violation_model,
)
from .power_b_validators import validate_candidate_model


def run_selfcheck() -> dict[str, object]:
    models = [
        build_smib_correct_model(),
        build_smib_power_violation_model(),
        build_smib_missing_closure_model(),
    ]
    results = {model.candidate_id: validate_candidate_model(model) for model in models}
    for candidate_id, report in results.items():
        print(f'[{candidate_id}] passed={report.passed} stage={report.stage}')
        for error in report.errors:
            print(f'  - {error.code}: {error.message}')
    return results


if __name__ == '__main__':
    pprint(run_selfcheck())
