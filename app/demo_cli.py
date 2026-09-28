from app.agent import OnCallCopilot
from app.seed_data import seed

NEW_INCIDENT_COLD = (
    "ALERT [prod] service=payments-api severity=P1\n"
    "502 Bad Gateway rate: 340/min (baseline: 2/min)\n"
    "Postgres logs: 'FATAL: sorry, too many clients already'\n"
    "Started: 3 minutes ago, during a marketing push notification blast."
)

NEW_INCIDENT_SIMILAR = (
    "ALERT [prod] service=search-api severity=P1\n"
    "502 Bad Gateway rate: 210/min (baseline: 1/min)\n"
    "Postgres logs: 'FATAL: sorry, too many clients already'\n"
    "Started: 90 seconds ago, during a scheduled reindex job."
)


def banner(text):
    print("\n" + "=" * 70)
    print(text)
    print("=" * 70)


def main():
    copilot = OnCallCopilot()

    banner("STEP 1: New incident hits an agent with EMPTY memory")
    r1 = copilot.handle_incident(NEW_INCIDENT_COLD)
    print(f"Memories found: {r1['memories_found']}")
    print(f"\nAgent diagnosis:\n{r1['diagnosis']}")

    banner("STEP 2: Seeding memory with past incident history")
    seed(copilot.hindsight, bank_id="oncall-copilot")

    banner("STEP 3: A NEW but similar incident hits the agent")
    r2 = copilot.handle_incident(NEW_INCIDENT_SIMILAR)
    print(f"Memories found: {r2['memories_found']}")
    print(f"\nRecalled memory:\n{r2['memory_text']}")
    print(f"\nAgent diagnosis:\n{r2['diagnosis']}")

    banner("STEP 4: Retaining this new resolution for next time")
    copilot.resolve_and_retain(
        NEW_INCIDENT_SIMILAR,
        "Same connection-pool exhaustion pattern as RB-DB-003. "
        "Applied pool size increase + try/finally fix to search-api. Resolved in 8 minutes.",
    )
    print("Retained. Next similar incident will be even faster.")


if __name__ == "__main__":
    main()