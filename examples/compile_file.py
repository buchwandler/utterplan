import argparse
from pathlib import Path

from utterplan import PlannerConfig, UtterancePlanner

DEFAULT_SOURCE = Path(__file__).with_name("chapter.ssmd")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile an SSMD file to an UtterancePlan.")
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"SSMD input file (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument("-o", "--output", type=Path, help="output plan path")
    args = parser.parse_args()

    source = args.source.read_text(encoding="utf-8")
    output = args.output or args.source.with_suffix(".utterplan.json")
    plan = UtterancePlanner(PlannerConfig(language="en-us", document_format="ssmd")).plan(source)
    plan.save(output)
    print(f"Saved {output}")


if __name__ == "__main__":
    main()
