"""Real process signals with synthetic jobs; no models, storage or database."""
import signal
import subprocess
import sys
from threading import Event

import pytest


@pytest.mark.parametrize('kind', [signal.SIGTERM, signal.SIGINT])
def test_shutdown_finishes_current_job_and_does_not_claim_another(tmp_path, kind):
    marker = tmp_path / 'finished'
    code = '''
import sys
from pathlib import Path
from types import SimpleNamespace
sys.modules['app.embeddings'] = SimpleNamespace(embed_many=lambda _: None)
marker = Path(sys.argv[1])
def job():
    print('processing', flush=True)
    sys.stdin.readline()
    marker.write_text('finalized')
    return True
sys.modules['app.ingestion_jobs'] = SimpleNamespace(process_one_job=job)
from scripts.ingestion_worker import main
sys.argv = [sys.argv[0], '--poll-seconds', '60']
main()
'''
    process = subprocess.Popen([sys.executable, '-u', '-c', code, str(marker)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == 'processing'
        process.send_signal(kind)
        output, errors = process.communicate('\n', timeout=5)
        assert process.returncode == 0, errors
        assert marker.read_text() == 'finalized'
        assert 'processing' not in output
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_shutdown_interrupts_idle_poll_without_waiting_sixty_seconds():
    code = '''
import sys
from types import SimpleNamespace
sys.modules['app.embeddings'] = SimpleNamespace(embed_many=lambda _: None)
def empty():
    print('idle', flush=True)
    return False
sys.modules['app.ingestion_jobs'] = SimpleNamespace(process_one_job=empty)
from scripts.ingestion_worker import main
sys.argv = [sys.argv[0], '--poll-seconds', '60']
main()
'''
    process = subprocess.Popen([sys.executable, '-u', '-c', code],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == 'idle'
        process.send_signal(signal.SIGTERM)
        _, errors = process.communicate(timeout=5)
        assert process.returncode == 0, errors
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_shutdown_during_warmup_prevents_claim_and_once_failure_still_propagates(monkeypatch):
    from scripts import ingestion_worker as worker
    stop = Event()
    monkeypatch.setattr(worker, 'embed_many', lambda _: stop.set())
    monkeypatch.setattr(worker, 'process_one_job', lambda: pytest.fail('No new claims after shutdown'))
    worker.run_worker(stop)
    stop.clear()
    monkeypatch.setattr(worker, 'embed_many', lambda _: None)
    def failure():
        raise ConnectionError('Synthetic queue failure')
    monkeypatch.setattr(worker, 'process_one_job', failure)
    with pytest.raises(ConnectionError):
        worker.run_worker(stop, once=True)
