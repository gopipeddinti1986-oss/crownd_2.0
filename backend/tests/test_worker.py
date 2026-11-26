import signal
from contextlib import nullcontext

from app import worker


def test_worker_writes_and_clears_heartbeat_on_graceful_shutdown(tmp_path, monkeypatch):
    heartbeat = tmp_path / "worker-heartbeat"
    handlers = {}
    writes = []
    monkeypatch.setattr("sys.argv", ["crownd-worker", "--poll-seconds", "0.5", "--heartbeat-file", str(heartbeat)])
    monkeypatch.setattr(worker.signal, "signal", lambda number, handler: handlers.__setitem__(number, handler))
    monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(object()))

    def poll(_db, *, batch_size):
        assert batch_size == 20
        worker._write_heartbeat(heartbeat)
        writes.append(heartbeat.exists())
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        return 0

    monkeypatch.setattr(worker, "process_due_deliveries", poll)
    assert worker.main() == 0
    assert writes == [True]
    assert not heartbeat.exists()
