"""Run the SQL-backed email delivery worker: `python -m app.worker`."""
import argparse
import logging
import os
from pathlib import Path
import signal
import time
from threading import Event

from app.core.config import settings
from app.database import SessionLocal
from app.services.notifications import process_due_deliveries

logging.basicConfig(level=getattr(logging, settings.log_level.upper()), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("crownd.notifications.worker")


def _write_heartbeat(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(str(int(time.time())), encoding="ascii")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Process CROWND's SQL email outbox")
    parser.add_argument("--once", action="store_true", help="process currently due messages and exit")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--heartbeat-file", default=settings.worker_heartbeat_file)
    args = parser.parse_args()
    if args.poll_seconds < 0.5 or args.batch_size < 1 or args.batch_size > 100:
        parser.error("poll-seconds must be at least 0.5 and batch-size must be 1..100")

    if args.once:
        with SessionLocal() as db:
            processed = process_due_deliveries(db, batch_size=args.batch_size)
        logger.info("One-shot poll completed processed=%d", processed)
        return 0

    heartbeat = Path(args.heartbeat_file)
    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        heartbeat.unlink(missing_ok=True)
        logger.info("Worker started poll_seconds=%.1f batch_size=%d", args.poll_seconds, args.batch_size)
        retry_delay = args.poll_seconds
        while not stop.is_set():
            try:
                with SessionLocal() as db:
                    processed = process_due_deliveries(db, batch_size=args.batch_size)
                _write_heartbeat(heartbeat)
                retry_delay = args.poll_seconds
                if processed:
                    logger.info("Processed outbox rows count=%d", processed)
            except Exception as exc:
                # Do not emit exception text/tracebacks: DB URLs and provider details can
                # be sensitive. A stale heartbeat lets the container healthcheck detect it.
                logger.error("Worker poll failed type=%s", type(exc).__name__)
                retry_delay = min(max(args.poll_seconds, retry_delay * 2), 60.0)
            stop.wait(retry_delay)
    finally:
        heartbeat.unlink(missing_ok=True)
        logger.info("Worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
