import threading
from pathlib import Path

from ccm.watcher.debounce import Debouncer
from ccm.watcher.stable import is_editor_temp, wait_until_stable, read_stable


def test_debounce_collapses_rapid_events():
    seen = []
    d = Debouncer(50, lambda p, k: seen.append((p, k)))
    d.submit("/tmp/a.json", "created")
    d.submit("/tmp/a.json", "modified")
    d.submit("/tmp/a.json", "modified")
    evt = threading.Event()

    def wait():
        while d.pending_count():
            evt.wait(0.01)
        evt.set()

    threading.Thread(target=wait).start()
    evt.wait(1.5)
    d.shutdown()
    assert len(seen) == 1
    assert seen[0][1] == "modified"


def test_editor_temp_and_stable(tmp_path: Path):
    assert is_editor_temp(tmp_path / ".foo.swp")
    assert is_editor_temp("file.json~")
    target = tmp_path / "c.json"
    target.write_text("{}", encoding="utf-8")
    assert wait_until_stable(target, 20, 500)
    data, err = read_stable(target, 20)
    assert err is None
    assert data == b"{}"
    missing, err2 = read_stable(tmp_path / "nope.json", 10)
    assert err2 == "missing"
