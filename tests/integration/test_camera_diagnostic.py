import importlib.util
from pathlib import Path
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parents[2] / 'scripts'))
import camera_diagnostic as camera


def test_disconnect_recovery_and_frozen_frame_metrics():
    _, encoded = cv2.imencode('.jpg', np.full((20, 20, 3), 128, np.uint8))
    replies = iter([(200, {'x-frame-id': '1'}, encoded.tobytes()), (503, {}, b''),
                    (200, {'x-frame-id': '2'}, encoded.tobytes()),
                    (200, {'x-frame-id': '2'}, encoded.tobytes())])
    tick = [0.0]
    def sleep(seconds):
        tick[0] += seconds
    stats = camera.sample('http://localhost:8000', 4, 1, get=lambda _: next(replies),
                          now=lambda: tick[0], sleep=sleep)
    assert stats['reads'] == 3 and stats['failures'] == 1
    assert stats['recoveries'] == 1 and stats['unique_frames'] == 2
    assert stats['observed_preview_fps'] == .5
