"""Operator-only dead-letter inspection/replay entry point.

This module is intentionally not exposed as an HTTP route. Run it inside the
worker environment with the deployment's operator identity.
"""

from __future__ import annotations

import argparse

from api.models import DeadLetterRecord
from workflow.orchestrator import SessionLocal
from workflow.outbox import replay_dead_letter


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect or replay Triphony dead letters")
    parser.add_argument("--replay")
    args = parser.parse_args()
    if args.replay:
        return 0 if replay_dead_letter(args.replay) else 1
    db = SessionLocal()
    try:
        for item in db.query(DeadLetterRecord).filter(DeadLetterRecord.resolved.is_(False)).order_by(DeadLetterRecord.last_failed_at).all():
            print(f"{item.id} {item.task_type} {item.failure_code} attempts={item.attempt_count} replay={item.replay_eligible}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
