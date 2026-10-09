from utterplan import PlannerConfig, UtterancePlanner


def main() -> None:
    plan = UtterancePlanner(PlannerConfig(language="en-us", document_format="ssmd")).plan(
        'Hello [Bonjour]{lang="fr"}.'
    )
    print([(segment.language, segment.text) for unit in plan.flow for segment in unit.segments])


if __name__ == "__main__":
    main()
