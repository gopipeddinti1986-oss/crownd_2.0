"""Run the SQL-backed email delivery worker: `python -m app.worker`."""
import argparse
import logging
import time

from app.database import SessionLocal
from app.services.notifications import process_due_deliveries

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("crownd.notifications.worker")


def main() -> None:
    parser = argparse.ArgumentParser(description="Process CROWND's SQL email outbox")
    parser.add_argument("--once", action="store_true", help="process currently due messages and exit")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args()
    if args.poll_seconds < 0.5 or args.batch_size < 1 or args.batch_size > 100:
        parser.error("poll-seconds must be at least 0.5 and batch-size must be 1..100")
    while True:
        with SessionLocal() as db:
            processed = process_due_deliveries(db, batch_size=args.batch_size)
        if processed:
            logger.info("Processed %d outbox rows", processed)
        if args.once:
            break
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
