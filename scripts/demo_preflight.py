#!/usr/bin/env python3
"""Read-only, loopback-only demo checks. No camera capture, TTS or message sends.

Exit 1 for FAIL, 0 otherwise; --strict also fails on WARN. No response bodies,
credentials, recipients or image contents are printed. OpenCV is optional.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MAX_BYTES = 8 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def local_url(value):
    p = urlsplit(value)
    if (p.scheme != 'http' or p.hostname not in {'localhost', '127.0.0.1', '::1'}
            or p.username or p.password or p.query or p.fragment or p.path not in ('', '/')):
        raise argparse.ArgumentTypeError('Use an HTTP loopback origin without credentials or a path')
    try:
        p.port
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Invalid port') from exc
    return value.rstrip('/')


def fetch(url, timeout=3):
    # Do not follow application redirects or system proxies with private local data.
    opener = build_opener(NoRedirect(), ProxyHandler({}))
    try:
        with opener.open(Request(url, method='GET'), timeout=timeout) as r:
            body = r.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                return 0, {}, b''
            return r.status, {k.lower(): v for k, v in r.headers.items()}, body
    except HTTPError as exc:
        return exc.code, {}, b''
    except (URLError, OSError, ValueError):
        return 0, {}, b''


def decode_frame(body):
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    if not body:
        return False
    frame = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or not frame.size:
        return False
    return float(frame[::8, ::8].mean()) >= 8


def check_database(path):
    """Never create or migrate a database. Do not read memory/setting contents."""
    try:
        with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=1) as db:
            if db.execute('PRAGMA quick_check(1)').fetchone() != ('ok',):
                return 'FAIL', 'SQLite integrity check failed; restore a known good database'
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'objects', 'snapshots', 'settings'} <= tables:
                return 'FAIL', 'SQLite schema incomplete; check the configured database path'
        return 'PASS', 'SQLite accessible and quick_check passed (read only)'
    except (sqlite3.Error, OSError, ValueError):
        return 'FAIL', 'SQLite unavailable; check --db matches CTRLF_DB_PATH and permissions'


def listener_check(port):
    try:
        r = subprocess.run(['lsof', '-t', '-iTCP:' + str(port), '-sTCP:LISTEN'],
                           capture_output=True, text=True, timeout=3)
        if r.returncode not in (0, 1):
            return 'WARN', 'Listener inspection unavailable'
        count = len(set(r.stdout.split()))
        if count > 1:
            return 'WARN', 'Multiple listener PIDs on backend port; inspect lsof before restarting'
        return ('PASS', 'One backend listener PID') if count == 1 else ('WARN', 'No backend listener PID visible')
    except (OSError, subprocess.TimeoutExpired):
        return 'WARN', 'Listener inspection unavailable (lsof required); other ports/processes not checked'


def run_checks(backend, frontend, *, get=fetch, sleep=time.sleep, interval=1,
               db=None, environ=None, listeners=listener_check):
    results = []
    def add(level, message):
        results.append((level, message))
    def endpoint(path, label, shape, optional=False):
        code, _, body = get(backend + path)
        if code != 200:
            add('WARN' if optional and code in (404, 405) else 'FAIL',
                f'{label}: ' + ('unavailable in this build' if code in (404, 405) else f'HTTP {code or "unreachable"}'))
            return None
        try:
            value = json.loads(body)
            if not isinstance(value, shape):
                raise ValueError()
        except (ValueError, TypeError, UnicodeError):
            add('FAIL', f'{label}: invalid response shape/JSON')
            return None
        add('PASS', label + ' accessible')
        return value

    health = endpoint('/api/health', 'Backend health', dict)
    if health is not None:
        active = health.get('camera') == 'active'
        add('PASS' if active else 'FAIL', 'Camera active' if active else 'Camera inactive; check source, permission and backend logs')
        if health.get('error'):
            add('FAIL', 'Backend reports an error; inspect local backend logs')
        if health.get('warning'):
            add('WARN', 'Backend reports a camera warning; inspect the dashboard')
        if health.get('model') and active and not health.get('error'):
            add('PASS', 'Detector model reported and camera active (frame advance checked separately)')
        else:
            add('WARN', 'Detector readiness unverified; check model load in backend logs')
        if health.get('undetectable'):
            add('WARN', 'Detector cannot recognize some catalog items; choose a supported demo object')
        if not health.get('capture_enabled'):
            add('WARN', 'Photo capture disabled; enable it before the visual-memory demo')
    frames = []
    for sample in range(2):
        if sample:
            sleep(interval)
        code, headers, body = get(backend + '/api/camera/frame')
        frames.append(headers.get('x-frame-id') if code == 200 else None)
        if code != 200:
            add('FAIL', f'Camera sample {sample + 1} unavailable; check camera connection')
            continue
        valid = decode_frame(body)
        if valid is None:
            add('WARN', 'Pixel check unavailable; install OpenCV/numpy in the backend environment')
        else:
            add('PASS' if valid else 'FAIL', f'Camera sample {sample + 1}: ' + ('decoded, not black' if valid else 'black or invalid JPEG'))
    if all(frames) and frames[0] != frames[1]:
        add('PASS', 'Processed frame ID advanced during sampling')
    else:
        add('WARN', 'Processed frame freshness unverified; frame ID missing or unchanged')
    if health is not None and health.get('status') != 'ok':
        add('FAIL', 'Health status is not ok')
    objects = endpoint('/api/objects', 'Memory/database API', list)
    if objects is not None:
        snaps = [o.get('snapshot') for o in objects if isinstance(o, dict) and isinstance(o.get('snapshot'), dict)]
        if snaps:
            sid = snaps[0].get('id')
            if type(sid) is not int or sid <= 0:
                add('FAIL', 'Snapshot has an invalid ID')
            else:
                code, _, body = get(backend + f'/api/snapshots/{sid}/image')
                ok = code == 200 and body.startswith(b'\xff\xd8')
                add('PASS' if ok else 'FAIL', 'Stored snapshot JPEG retrievable' if ok else 'Stored snapshot reference is broken; inspect writer logs/disk')
        else:
            add('WARN', 'No stored snapshot yet; show a supported object and wait for capture')
    observations = endpoint('/api/observations', 'Wearable observations', list, optional=True)
    if isinstance(observations, list):
        for ev in observations[:20]:
            if not isinstance(ev, dict):
                add('FAIL', 'Observation payload is not an object')
                break
            sid = ev.get('snapshot_id')
            if sid is not None:
                if type(sid) is not int or sid <= 0:
                    add('FAIL', 'Observation snapshot ID is invalid')
                    break
                code, _, body = get(backend + f'/api/snapshots/{sid}/image')
                if code != 200 or not body.startswith(b'\xff\xd8'):
                    add('FAIL', 'Observation photo reference unavailable; check retention/writer logs')
                    break
        else:
            if observations:
                add('PASS', 'Sampled observation photo references resolve (up to 20 records)')
    if observations == []:
        add('WARN', 'No wearable observations recorded yet')
    endpoint('/api/voice', 'Voice settings', dict, optional=True)
    reminder_settings = endpoint('/api/reminders/settings', 'Reminder policy settings', dict, optional=True)
    if reminder_settings is not None:
        add('WARN', 'Reminder policy accessible; Photon agent connection and handset receipt still unverified')
    else:
        add('WARN', 'Legacy departure readiness unverified; inspect the agent locally (its GET routes can emit events)')
    env = os.environ if environ is None else environ
    configured = all(env.get(k) for k in ('PROJECT_ID', 'PROJECT_SECRET', 'ALERT_RECIPIENTS'))
    add('WARN', 'Photon configuration present in this shell; agent connectivity/delivery unverified' if configured
        else 'Photon configuration not visible in this shell; check the agent environment privately')
    code, headers, body = get(frontend)
    html = 'text/html' in headers.get('content-type', '') and b'<html' in body.lower()
    add('PASS' if code == 200 and html else 'FAIL', 'Frontend HTML reachable' if code == 200 and html else 'Frontend unavailable or not HTML; start Vite/check --frontend')
    code, _, body = get(frontend + '/api/health')
    try:
        proxy_health = json.loads(body)
        proxy_ok = code == 200 and proxy_health.get('status') == 'ok'
        if health is not None:
            keys = ('view_id', 'camera', 'camera_mode', 'model')
            proxy_ok = proxy_ok and all(proxy_health.get(k) == health.get(k) for k in keys)
    except (ValueError, TypeError, AttributeError, UnicodeError):
        proxy_ok = False
    add('PASS' if proxy_ok else 'FAIL', 'Frontend API proxy reachable' if proxy_ok else 'Frontend API proxy unavailable or targets another backend; check Vite proxy target/port')
    if db:
        add(*check_database(db))
    else:
        add('WARN', 'Direct SQLite check skipped; pass --db with the actual CTRLF_DB_PATH')
    add(*listeners(urlsplit(backend).port or 80))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', type=local_url, default='http://127.0.0.1:8000')
    parser.add_argument('--frontend', type=local_url, default='http://127.0.0.1:5173')
    parser.add_argument('--db', type=Path)
    parser.add_argument('--interval', type=float, default=1)
    parser.add_argument('--strict', action='store_true')
    args = parser.parse_args(argv)
    if not 0.1 <= args.interval <= 30:
        parser.error('--interval must be between 0.1 and 30 seconds')
    results = run_checks(args.backend, args.frontend, interval=args.interval, db=args.db)
    for level, message in results:
        print(f'{level} — {message}')
    return int(any(level == 'FAIL' or (args.strict and level == 'WARN') for level, _ in results))


if __name__ == '__main__':
    raise SystemExit(main())
