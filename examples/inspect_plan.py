import argparse
from pathlib import Path

from utterplan import FlowPlan

DEFAULT_PLAN = Path(__file__).with_name("example.utterplan.toml")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a FlowPlan file.")
    parser.add_argument(
        "plan",
        nargs="?",
        type=Path,
        default=DEFAULT_PLAN,
        help=f"plan file (default: {DEFAULT_PLAN}; run basic.py first)",
    )
    args = parser.parse_args()

    if not args.plan.exists():
        parser.error(f"plan file not found: {args.plan}; run basic.py first or provide a path")

    plan = FlowPlan.load(args.plan)
    for unit in plan.flow:
        for segment in unit.segments:
            print(segment.text, segment.language, segment.pause_before, segment.pause_after)


if __name__ == "__main__":
    main()
