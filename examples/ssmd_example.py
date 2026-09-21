from utterplan import PlannerConfig, UtterancePlanner


def main() -> None:
    plan = UtterancePlanner(PlannerConfig(language="en-us", document_format="ssmd")).plan(
        "Hello ...s world"
    )
    print(plan.to_json())


if __name__ == "__main__":
    main()
