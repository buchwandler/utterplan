from pathlib import Path

from utterplan import PlannerConfig, UtterancePlanner

OUTPUT = Path(__file__).with_name("example.utterplan.json")


def main() -> None:
    plan = UtterancePlanner(PlannerConfig(language="en-us", document_format="plain")).plan(
        "Doctor Smith bought 5 kg of apples."
    )
    plan.save(OUTPUT)
    print(f"{plan.plan_id}\nSaved {OUTPUT}")


if __name__ == "__main__":
    main()
