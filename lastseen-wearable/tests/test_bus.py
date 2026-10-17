import threading

from lastseen.bus import Bus


def test_publish_reaches_subscriber():
    b = Bus()
    q = b.subscribe()
    b.publish("event", x=1)
    m = q.get(timeout=1)
    assert m["type"] == "event" and m["x"] == 1 and "ts" in m


def test_unsubscribe_stops_delivery():
    b = Bus()
    q = b.subscribe()
    b.unsubscribe(q)
    b.publish("event", x=1)
    assert q.empty()


def test_slow_subscriber_drops_oldest():
    b = Bus()
    q = b.subscribe()
    for i in range(205):
        b.publish("event", i=i)
    assert q.qsize() == 200
    assert q.get_nowait()["i"] == 5


def test_threaded_publish():
    b = Bus()
    q = b.subscribe()
    ts = [threading.Thread(target=lambda: [b.publish("e") for _ in range(20)]) for _ in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert q.qsize() == 100
