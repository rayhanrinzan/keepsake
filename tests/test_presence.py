from conftest import obs
from presence import PresenceTracker

FPS = 0.2  # seconds per frame, like the live worker


def feed(tracker, n, observations, t):
    out = []
    for _ in range(n):
        out.append(tracker.update(observations, now=t))
        t += FPS
    return [e for e in out if e], t


def person(conf=0.8):
    return obs("person", conf=conf, size=0.4)


def test_person_entering_then_leaving_fires_one_left_event():
    p = PresenceTracker(enter_frames=3, leave_seconds=2.0)
    events, t = feed(p, 10, [person()], 0.0)
    assert events == ["entered"] and p.present
    events, t = feed(p, 15, [], t)  # 3 s gone
    assert events == ["left"] and not p.present
    assert p.left_count == 1 and p.left_at is not None


def test_brief_dropout_does_not_count_as_leaving():
    p = PresenceTracker(enter_frames=3, leave_seconds=2.0)
    _, t = feed(p, 10, [person()], 0.0)
    events, t = feed(p, 5, [], t)  # 1 s missed detections
    events2, t = feed(p, 5, [person()], t)
    assert events == [] and events2 == [] and p.left_count == 0


def test_single_frame_false_positive_never_enters():
    p = PresenceTracker(enter_frames=3, leave_seconds=2.0)
    events, t = feed(p, 1, [person()], 0.0)
    events2, _ = feed(p, 20, [], t)
    assert events == [] and events2 == [] and p.left_count == 0


def test_low_confidence_people_and_other_items_are_ignored():
    p = PresenceTracker(enter_frames=3, leave_seconds=2.0, min_conf=0.35)
    events, _ = feed(p, 10, [person(conf=0.2), obs("bottle")], 0.0)
    assert events == [] and not p.present


def test_reset_forgets_presence_without_firing():
    p = PresenceTracker(enter_frames=3, leave_seconds=2.0)
    _, t = feed(p, 10, [person()], 0.0)
    p.reset()
    events, _ = feed(p, 20, [], t)
    assert events == [] and not p.present
