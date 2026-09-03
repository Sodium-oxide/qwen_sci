"""Command-line entry points limited to the new role-A package."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import json

from .pipeline import run_offline_b0_slice, verify_result_bundle, verify_result_bundle_by_id


def _parser() -> ArgumentParser:
    parser = ArgumentParser(prog="power-core-a")
    subcommands = parser.add_subparsers(dest="command", required=True)

    run = subcommands.add_parser("run-b0", help="Run the deterministic no-LLM B0 role-A slice")
    run.add_argument("--store", type=Path, required=True)
    run.add_argument(
        "--fixtures",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "examples_power_core_a" / "b0",
    )
    run.add_argument("--run-id", default="run_b0_offline_001")
    run.add_argument("--approval", type=Path, help="Optional external ApprovalRecord JSON")
    run.add_argument(
        "--require-external-approval",
        action="store_true",
        help="Stop at APPROVAL_PENDING and emit a hash-bound approval template",
    )

    verify = subcommands.add_parser("verify-bundle", help="Verify an immutable Result Bundle")
    verify.add_argument("--store", type=Path, required=True)
    source = verify.add_mutually_exclusive_group(required=True)
    source.add_argument("--descriptor", type=Path)
    source.add_argument("--bundle-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "run-b0":
        approval = (
            json.loads(args.approval.read_text(encoding="utf-8"))
            if args.approval else None
        )
        result = run_offline_b0_slice(
            store_root=args.store, fixture_dir=args.fixtures, run_id=args.run_id,
            approval_record=approval,
            auto_approve_fixture=not args.require_external_approval,
        )
    elif args.bundle_id:
        result = verify_result_bundle_by_id(
            store_root=args.store, bundle_id=args.bundle_id
        )
    else:
        descriptor = json.loads(args.descriptor.read_text(encoding="utf-8"))
        result = verify_result_bundle(store_root=args.store, bundle_descriptor=descriptor)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
