#!/usr/bin/env python3
"""Sample the backend preview without claiming or opening the camera device.

Counts preview HTTP successes/failures, unique processed frames, black/invalid
JPEGs and observed recovery. The preview is annotated; raw sensor FPS and exact
last sensor-read time are not exposed by the current API.
"""
import argparse
import time

from demo_preflight import decode_frame, fetch, local_url


def sample(backend, seconds, interval, *, get=fetch, now=time.monotonic, sleep=time.sleep):
    start = now()
    last_valid = None
    last_id = None
    stats = dict(reads=0, failures=0, unique_frames=0, black_or_invalid=0, recoveries=0,
                 pixel_check_unavailable=0)
    failing = False
    while now() - start < seconds:
        code, headers, body = get(backend + '/api/camera/frame')
        valid = decode_frame(body) if code == 200 else False
        if code == 200 and valid is not False:
            stats['reads'] += 1
            stats['pixel_check_unavailable'] += valid is None
            fid = headers.get('x-frame-id')
            if fid is not None and fid != last_id:
                stats['unique_frames'] += 1
            last_id = fid
            last_valid = now()
            if failing:
                stats['recoveries'] += 1
            failing = False
        else:
            stats['failures'] += 1
            stats['black_or_invalid'] += code == 200
            failing = True
        sleep(interval)
    elapsed = max(now() - start, .001)
    stats['sample_seconds'] = round(elapsed, 2)
    stats['observed_preview_fps'] = round(stats['unique_frames'] / elapsed, 2)
    stats['seconds_since_valid_sample'] = None if last_valid is None else round(now() - last_valid, 2)
    return stats


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backend', type=local_url, default='http://127.0.0.1:8000')
    p.add_argument('--seconds', type=float, default=15)
    p.add_argument('--interval', type=float, default=.2)
    args = p.parse_args()
    if not 1 <= args.seconds <= 300 or not .1 <= args.interval <= 10:
        p.error('Use --seconds 1..300 and --interval 0.1..10')
    print('Passive backend-preview sampling; no direct camera access. Ctrl+C stops sampling.')
    try:
        stats = sample(args.backend, args.seconds, args.interval)
    except KeyboardInterrupt:
        return 130
    for name, value in stats.items():
        print(f'{name}: {value}')
    print('Observed preview FPS is bounded by polling frequency, not sensor or inference FPS.')
    return int(stats['failures'] > 0 or stats['unique_frames'] < 2)


if __name__ == '__main__':
    raise SystemExit(main())
