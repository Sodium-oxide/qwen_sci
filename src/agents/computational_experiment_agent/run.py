"""Small API and CLI for the optional B branch."""

import argparse
import json
from pathlib import Path

from .orchestrator import ComputationalOrchestrator


def run_computational_experiment(run_dir, *, context, mode="off", budget=None, llm_call=None):
    return ComputationalOrchestrator(run_dir, llm_call=llm_call).start(context=context, mode=mode, budget=budget)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--mode", choices=("off", "plan", "run"), default="off")
    parser.add_argument("--context")
    parser.add_argument("--owner-pid", type=int)
    parser.add_argument("--owner-create-time", type=float)
    parser.add_argument("--parent-pid", type=int)
    parser.add_argument("--parent-create-time", type=float)
    parser.add_argument("action", nargs="?", choices=("start", "resume", "status", "cancel", "worker", "watch"), default="start")
    args = parser.parse_args(argv)
    controller = ComputationalOrchestrator(Path(args.run_dir))
    if args.action == "watch":
        from src.pipeline.computational_workflow import watch_branch
        if args.owner_pid is None or args.owner_create_time is None:
            parser.error("watch requires owner identity")
        parent_identity = {"pid": args.parent_pid, "create_time": args.parent_create_time} if args.parent_pid is not None else None
        watch_branch(Path(args.run_dir), {"pid": args.owner_pid, "create_time": args.owner_create_time}, parent_identity)
        return 0
    if args.action == "worker":
        from src.pipeline.computational_workflow import worker
        result = worker(Path(args.run_dir))
    elif args.action == "start":
        if not args.context:
            parser.error("start requires --context")
        context = json.loads(Path(args.context).read_text(encoding="utf-8"))
        result = controller.start(context=context, mode=args.mode)
    elif args.action == "resume":
        result = controller.resume()
    elif args.action == "cancel":
        from src.pipeline.computational_state import request_cancel
        result = request_cancel(controller.branch)
    else:
        from src.pipeline.computational_state import load_state
        result = load_state(controller.branch)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
