"""The app must exit promptly on Ctrl+C even while a /stream (MJPEG) client is connected.

Runs the real entry point in a subprocess with the fake tracker (no ML models), a replay
video, voice off and a free port (LASTSEEN_PORT).
"""
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_up(port: int, proc, timeout: float = 60.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            pytest.fail(f"app exited early with {proc.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5) as s:
                s.sendall(b"GET /health HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
                if s.recv(64).startswith(b"HTTP/1.1 200"):
                    return
        except OSError:
            pass
        time.sleep(0.2)
    pytest.fail("app did not come up")


@pytest.fixture
def app_config(tmp_path):
    video = tmp_path / "syn.mp4"
    w = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 15, (320, 240))
    for i in range(30):
        f = np.full((240, 320, 3), 90, np.uint8)
        cv2.circle(f, (20 + i * 9, 120), 15, (255, 255, 255), -1)
        w.write(f)
    w.release()
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    cfg["camera"]["replay_video"] = str(video)
    cfg["features"].update(voice=False, fake_tracker=True)
    cfg["paths"] = {"data": str(tmp_path / "data"), "models": str(tmp_path / "models")}
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_exits_promptly_with_stream_client(app_config, sig, tmp_path):
    port = _free_port()
    env = {**os.environ, "LASTSEEN_CONFIG": str(app_config), "LASTSEEN_PORT": str(port)}
    err = open(tmp_path / "stderr.log", "w+")
    proc = subprocess.Popen([sys.executable, "-m", "lastseen"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=err)
    stream = None
    try:
        _wait_up(port, proc)
        stream = socket.create_connection(("127.0.0.1", port), timeout=5)
        stream.sendall(b"GET /stream HTTP/1.1\r\nHost: x\r\n\r\n")
        assert stream.recv(64).startswith(b"HTTP/1.1 200")
        t0 = time.time()
        proc.send_signal(sig)
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            pytest.fail("app still running 8 s after the signal")
        assert time.time() - t0 < 6
        err.seek(0)
        assert "Traceback" not in err.read()  # streams end cleanly, not by forced cancel
    finally:
        if stream is not None:
            stream.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        err.close()
