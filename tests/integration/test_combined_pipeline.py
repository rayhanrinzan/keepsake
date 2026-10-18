"""Merged production path: real event/store/API/policy, synthetic frames, no device/network."""
import importlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

import events as E
from catalog import BY_CATEGORY
from memory import Observation
from wearable import WearableObserver
from vision import VisionWorker

T0 = datetime(2026, 10, 17, 20, 0, tzinfo=timezone.utc)
LOCAL = {'X-Keepsake-Local': '1'}


@pytest.fixture
def combined(tmp_path, monkeypatch):
    values = {'CAMERA_ENABLED': '0', 'REMINDERS_THREAD': '0',
              'DB_PATH': str(tmp_path/'memory.db'), 'SNAPSHOT_DIR': str(tmp_path/'photos'),
              'ENV_FILE': str(tmp_path/'missing.env')}
    for name, value in values.items():
        monkeypatch.setenv('CTRLF_' + name, value)
    monkeypatch.delenv('XAI_API_KEY', raising=False)
    import main
    main = importlib.reload(main)
    clock = [T0.timestamp()]
    main.reminders.clock = lambda: clock[0]
    frame = np.full((80, 120, 3), 128, np.uint8)
    worker = SimpleNamespace(memory=main.memory, snapshots=main.snapshots,
                             _frame_for=lambda _: frame)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        yield SimpleNamespace(main=main, client=client, clock=clock, worker=worker, frame=frame)


def event(w, kind='object_observed', category='bottle', at=None):
    item = BY_CATEGORY[category]
    evidence = ['stable_object_detection', 'camera_steady']
    if kind == 'possible_pickup':
        evidence += ['hand_near_object', 'object_moved_with_hand']
    if kind == 'placement_confirmed':
        evidence += ['prior_possible_pickup', 'hand_released']
    return E.make_event(kind, object_id=item['object_id'], category=category, name=item['name'],
        timestamp=at or datetime.fromtimestamp(w.clock[0], timezone.utc), confidence=.9,
        bbox=(.1, .2, .2, .3), frame_id=1, view_id=w.main.memory.view_id, evidence=evidence)


def record(w, ev):
    VisionWorker._record(w.worker, ev)
    w.main.snapshots.flush()


def enable(w, mode='high_assistance'):
    r = w.client.put('/api/reminders/settings', headers=LOCAL,
        json={'enabled': True, 'mode': mode, 'opt_in': True, 'important': ['bottle']})
    assert r.status_code == 200


def queue(w):
    enable(w)
    record(w, event(w))
    w.main.reminders.tick()
    w.clock[0] += 20
    alerts = w.main.reminders.tick()
    assert len(alerts) == 1
    return alerts[0]


def test_early_wearable_photo_retrievable_before_spatial_memory_settles(combined):
    w = combined
    observer = WearableObserver()
    o = Observation('bottle', .9, .15, .25, bbox=(.1, .2, .2, .3))
    produced = []
    for fid in range(1, 4):
        produced += observer.update([o], T0+timedelta(seconds=fid*.2), fid, view_id=w.main.memory.view_id)
    assert len(produced) == 1
    record(w, produced[0])
    assert w.main.db.get_by_category('bottle') is None
    result = w.client.post('/api/query', json={'text': 'water bottle'}).json()
    assert result['found'], result
    assert result['object']['seen'] and result['object']['snapshot']
    assert w.client.get(result['object']['snapshot']['image_url']).status_code == 200
    assert 'side of' not in result['answer']


def test_observation_photo_reminder_claim_result(combined):
    w = combined
    alert = queue(w)
    item = alert['items'][0]
    assert item['object_id'] == 'bottle_01' and item['place'] is None
    assert w.client.get(f"/api/snapshots/{item['snapshot_id']}/image").status_code == 200
    url = f"/api/reminders/alerts/{alert['id']}"
    assert w.client.post(url+'/claim', headers=LOCAL).status_code == 200
    assert w.client.post(url+'/claim', headers=LOCAL).status_code == 409
    assert w.client.post(url+'/result', headers=LOCAL, json={'status':'accepted'}).json()['status'] == 'accepted'
    assert w.client.get('/api/reminders/alerts').json() == []
    assert w.main.reminders.tick() == []


@pytest.mark.parametrize('change', ['pickup', 'delete_photo', 'camera_down'])
def test_claim_rechecks_grounding_after_queue(combined, change):
    w = combined
    alert = queue(w)
    if change == 'pickup':
        w.main.reminders.submit(event(w, 'possible_pickup'))
    elif change == 'delete_photo':
        row = w.main.db.get_snapshot(alert['items'][0]['snapshot_id'])
        w.main.snapshots.path_for(row['filename']).unlink()
    else:
        w.main.reminders.status_fn = lambda: {'camera': 'error'}
    r = w.client.post(f"/api/reminders/alerts/{alert['id']}/claim", headers=LOCAL)
    assert r.status_code == 409, r.json()


def test_older_placement_cannot_replace_newer_episode(combined):
    w = combined
    enable(w, 'everyday')
    newer = event(w, 'placement_confirmed')
    w.main.reminders.submit(newer)
    w.main.reminders.submit(event(w, 'placement_confirmed', at=T0-timedelta(seconds=10)))
    assert w.main.reminders._objs['bottle_01'].episode == newer['event_id']


@pytest.mark.parametrize('timestamp', [123, [], {}, True])
def test_malformed_event_is_422(combined, timestamp):
    ev = event(combined)
    ev['timestamp'] = timestamp
    assert combined.client.post('/api/reminders/events', headers=LOCAL, json=ev).status_code == 422


def test_delayed_snapshot_callback_unblocks_same_episode(combined, monkeypatch):
    import threading
    w = combined
    enable(w)
    entered, release = threading.Event(), threading.Event()
    write = w.main.snapshots._write
    def delayed(*args):
        entered.set()
        assert release.wait(3)
        return write(*args)
    monkeypatch.setattr(w.main.snapshots, '_write', delayed)
    ev = event(w)
    try:
        VisionWorker._record(w.worker, ev)
        assert entered.wait(2)
        assert w.main.db.get_observations()[0]['snapshot_id'] is None
        assert w.main.reminders.tick() == []
        assert w.main.reminders._objs['bottle_01'].episode == ev['event_id']
    finally:
        release.set()
        w.main.snapshots.flush()
    w.clock[0] += 20
    queued = w.main.reminders.tick()
    assert len(queued) == 1 and queued[0]['items'][0]['episode'] == ev['event_id']


def test_observation_backlog_does_not_skip_oldest_events(combined):
    w = combined
    for i in range(205):
        ev = event(w, at=T0+timedelta(milliseconds=i))
        w.main.db.add_observation(ev)
    w.clock[0] += 1
    w.main.reminders.tick()
    assert w.main.reminders._observation_cursor == 200
    w.main.reminders.tick()
    assert w.main.reminders._observation_cursor == 205
    assert len(w.main.reminders._seen_events) == 205


def test_cancelling_one_item_keeps_other_batch_item(combined):
    w = combined
    enable(w)
    w.client.put('/api/reminders/settings', headers=LOCAL, json={'important':['bottle','wallet']})
    record(w, event(w))
    record(w, event(w, category='wallet'))
    w.main.reminders.tick()
    w.clock[0] += 20
    alert = w.main.reminders.tick()[0]
    assert len(alert['items']) == 2
    w.main.reminders.ingest(event(w, 'possible_pickup'))  # not yet processed by the background tick
    claimed = w.client.post(f"/api/reminders/alerts/{alert['id']}/claim", headers=LOCAL)
    assert claimed.status_code == 200
    assert [i['object_id'] for i in claimed.json()['items']] == ['wallet_01']


def test_voice_tts_uses_grounded_query_answer_without_grok_network(combined):
    w = combined
    record(w, event(w))
    result = w.client.post('/api/query', json={'text':'water bottle'}).json()
    spoken = []
    def synthesize(text, voice_id, speed):
        spoken.append(text)
        return b'ID3-test-only'
    w.main.grok = SimpleNamespace(synthesize=synthesize)
    r = w.client.post('/api/tts', json={'text': result['answer']})
    assert r.status_code == 200 and r.content == b'ID3-test-only'
    assert spoken == [result['answer']]
    assert w.client.post('/api/query', json={'text':'umbrella'}).json()['found'] is False


def test_node_agent_against_real_fastapi(combined):
    """Opt-in loopback server; notifier is still entirely fake, no Photon SDK imported."""
    import os
    import socket
    import subprocess
    import threading
    import time
    from pathlib import Path
    import uvicorn
    if os.getenv('KEEPSAKE_HTTP_E2E') != '1':
        pytest.skip('Set KEEPSAKE_HTTP_E2E=1 for loopback Python/TypeScript bridge test')
    w = combined
    queue(w)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(w.main.app, lifespan='off', log_level='error'))
    thread = threading.Thread(target=server.run, kwargs={'sockets':[listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic()+5
        while not server.started and time.monotonic()<deadline:
            time.sleep(.02)
        assert server.started
        root = Path(__file__).parents[2]
        result = subprocess.run(['node', '--import', str(root/'integrations/photon/node_modules/tsx/dist/loader.mjs'),
            '--test', str(Path(__file__).with_name('delivery_bridge.test.mts'))],
            cwd=root, env={**os.environ, 'KEEPSAKE_QA_URL':f'http://127.0.0.1:{port}',
                'TSX_TSCONFIG_PATH':str(root/'frontend/tsconfig.app.json')},
            capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout+result.stderr
        assert w.main.reminders.alerts('accepted')
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()
        assert not thread.is_alive()


def test_wearable_does_not_expose_stationary_departure_prompt_counter(combined):
    w = combined
    w.main.worker = SimpleNamespace(status={'camera':'active','person_left_count':4},
                                    stop=lambda:None, join=lambda **_:None)
    assert w.client.get('/api/health').json()['person_left_count'] == 0
    w.main.worker = None


def test_newer_observation_updates_existing_memory_time(combined):
    w = combined
    from conftest import Clock, obs
    Clock(w.main.memory, start=T0-timedelta(minutes=2)).frames(6, obs('bottle'))
    assert w.main.db.get_by_category('bottle') is not None
    newer = event(w)
    record(w, newer)
    result = w.client.post('/api/query', json={'text':'bottle'}).json()
    assert result['object']['last_seen'] == newer['timestamp']
    assert 'region' not in result['object']


def test_pickup_inference_does_not_fabricate_a_visual_memory(combined):
    w = combined
    record(w, event(w, 'possible_pickup'))
    assert w.client.post('/api/query', json={'text':'bottle'}).json()['found'] is False


def test_retrieval_uses_event_time_and_ignores_newer_pickup_inference(combined):
    w = combined
    latest = event(w)
    record(w, latest)
    record(w, event(w, at=T0-timedelta(seconds=5)))
    record(w, event(w, 'possible_pickup', at=T0+timedelta(seconds=10)))
    result = w.client.post('/api/query', json={'text':'bottle'}).json()
    assert result['object']['last_seen'] == latest['timestamp']


def test_latest_visual_event_keeps_its_matching_photo_when_events_arrive_late(combined):
    w = combined
    w.main.snapshots.cooldown = 0
    latest = event(w)
    record(w, latest)
    photo_id = w.main.db.latest_sighting('bottle_01')['snapshot_id']
    record(w, event(w, at=T0-timedelta(seconds=5)))
    result = w.client.post('/api/query', json={'text':'bottle'}).json()
    assert result['object']['snapshot']['id'] == photo_id


def test_missing_files_are_not_null_entries_in_photo_history(combined):
    w = combined
    record(w, event(w))
    photo = w.main.db.get_snapshots('bottle_01')[0]
    w.main.snapshots.path_for(photo['filename']).unlink()
    assert w.client.get('/api/objects/bottle_01/snapshots').json() == []


def test_wearable_objects_carry_no_room_position(combined):
    """A worn camera's screen position is where the wearer looked; the Map must not pin it."""
    w = combined
    record(w, event(w))
    w.main.db.upsert_object({'object_id': 'bottle_01', 'category': 'bottle', 'name': 'Water Bottle',
                             'region': 'Couch', 'x': .4, 'y': .6, 'visible': False,
                             'last_seen': T0.isoformat(), 'confidence': .9,
                             'view_id': w.main.memory.view_id, 'lost_while_moving': False})
    o = w.client.get('/api/objects/bottle').json()
    assert o['seen'] and o['snapshot'] is not None
    assert not {'region', 'x', 'y'} & set(o)
