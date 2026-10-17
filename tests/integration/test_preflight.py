"""Preflight exercises HTTP failures without opening devices or sending messages."""
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

spec = importlib.util.spec_from_file_location('preflight', Path(__file__).parents[2] / 'scripts/demo_preflight.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def test_unfinished_build_is_actionable_and_private():
    calls = []
    def get(url):
        calls.append(url)
        if url.endswith('/api/health'):
            return 200, {}, json.dumps({'camera': 'disabled', 'error': 'secret +15555555555'}).encode()
        return 404, {}, b'private backend error'
    results = p.run_checks('http://localhost:8000', 'http://localhost:5173', get=get,
                           sleep=lambda _: None, environ={'PROJECT_SECRET': 'secret'},
                           listeners=lambda _: ('WARN', 'not inspected'))
    rendered = str(results)
    assert 'unavailable in this build' in rendered
    assert 'secret' not in rendered and '+15555555555' not in rendered
    assert all('/simulate' not in c and '/tts' not in c and '/api/departures' not in c for c in calls)
    assert any(level == 'FAIL' for level, _ in results)


def test_frames_must_advance_and_snapshot_must_exist():
    _, encoded = cv2.imencode('.jpg', np.full((20, 20, 3), 120, np.uint8))
    def get(url):
        if url.endswith('/api/camera/frame'):
            return 200, {'x-frame-id': '4'}, encoded.tobytes()
        if url.endswith('/api/objects'):
            return 200, {}, b'[{"snapshot":{"id":1,"image_url":"https://evil.invalid"}}]'
        return 404, {}, b''
    results = p.run_checks('http://localhost:8000', 'http://localhost:5173', get=get,
                           sleep=lambda _: None, environ={}, listeners=lambda _: ('WARN', 'not inspected'))
    assert ('FAIL', 'Stored snapshot reference is broken; inspect writer logs/disk') in results
    assert any('freshness unverified' in msg for _, msg in results)


@pytest.mark.parametrize('body', [b'', b'not jpeg'])
def test_invalid_frames(body):
    # OpenCV rejects empty buffers before returning None.
    assert p.decode_frame(body) is False


def test_black_frame():
    _, encoded = cv2.imencode('.jpg', np.zeros((20, 20, 3), np.uint8))
    assert p.decode_frame(encoded.tobytes()) is False


def test_database_check_does_not_create_file(tmp_path):
    missing = tmp_path / 'missing.db'
    assert p.check_database(missing)[0] == 'FAIL'
    assert not missing.exists()


@pytest.mark.parametrize('url', ['https://localhost', 'http://example.com', 'http://user:secret@localhost', 'http://localhost/api', 'http://localhost:bad'])
def test_only_local_origins(url):
    with pytest.raises(Exception):
        p.local_url(url)


def test_healthy_build_and_proxy():
    frame_id = [0]
    _, encoded = cv2.imencode('.jpg', np.full((20, 20, 3), 120, np.uint8))
    def get(url):
        if url.endswith('/api/health'):
            return 200, {}, b'{"status":"ok","camera":"active","model":"test","capture_enabled":true}'
        if url.endswith('/api/camera/frame'):
            frame_id[0] += 1
            return 200, {'x-frame-id': str(frame_id[0])}, encoded.tobytes()
        if url.endswith('/api/objects'):
            return 200, {}, b'[{"snapshot":{"id":1}}]'
        if url.endswith('/api/snapshots/1/image'):
            return 200, {}, encoded.tobytes()
        if url.endswith('/api/observations'):
            return 200, {}, b'[{"snapshot_id":1}]'
        if url.endswith('/api/voice') or url.endswith('/api/departures/context') or url.endswith('/api/reminders/settings'):
            return 200, {}, b'{}'
        return 200, {'content-type': 'text/html'}, b'<html>app</html>'
    results = p.run_checks('http://localhost:8000', 'http://localhost:5173', get=get,
        sleep=lambda _: None, environ={}, listeners=lambda _: ('PASS', 'One listener'))
    assert not any(level == 'FAIL' for level, _ in results)
    assert ('PASS', 'Frontend API proxy reachable') in results
    assert ('PASS', 'Processed frame ID advanced during sampling') in results


def test_proxy_pointing_at_other_backend_is_failure():
    def get(url):
        if url == 'http://localhost:8000/api/health':
            return 200, {}, b'{"status":"ok","camera":"disabled","view_id":"a"}'
        if url == 'http://localhost:5173/api/health':
            return 200, {}, b'{"status":"ok","camera":"active","view_id":"b"}'
        return 404, {}, b''
    results = p.run_checks('http://localhost:8000', 'http://localhost:5173', get=get,
        sleep=lambda _: None, environ={}, listeners=lambda _: ('WARN', 'not inspected'))
    assert any(level == 'FAIL' and 'another backend' in msg for level, msg in results)
