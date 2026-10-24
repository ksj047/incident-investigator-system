"""Backend API tests: the HTTP server is started in-process on a free port."""
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server.app import Handler  # noqa: E402


@pytest.fixture(scope="module")
def base():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def get_json(url):
    return json.loads(get(url)[2])


def status_of(url):
    try:
        return get(url)[0]
    except urllib.error.HTTPError as e:
        return e.code


def test_health_and_frontend(base):
    h = get_json(f"{base}/api/health")
    assert h["status"] == "ok" and h["incidents"] >= 10 and h["backends"]["offline"]
    code, ctype, body = get(f"{base}/")
    assert code == 200 and "text/html" in ctype and b"Incident Investigator" in body
    assert get(f"{base}/static/app.js")[0] == 200


def test_incident_endpoints_never_expose_ground_truth(base):
    lst = get_json(f"{base}/api/incidents")
    assert {"id", "title", "severity", "reported_service"} <= set(lst[0])
    one = get(f"{base}/api/incidents/INC-002")[2].decode()
    assert "root_cause_service" not in one and "key_evidence" not in one and '"faults"' not in one


def test_bad_requests(base):
    assert status_of(f"{base}/api/incidents/INC-999") == 404
    assert status_of(f"{base}/api/investigate?incident=INC-001&mode=bogus") == 400
    assert status_of(f"{base}/static/../../data/ground_truth/INC-001.json") in (403, 404)
    assert status_of(f"{base}/api/eval/..") == 404


def test_investigation_stream_and_scoring(base):
    events = []
    with urllib.request.urlopen(f"{base}/api/investigate?incident=INC-002&mode=multi&backend=offline", timeout=60) as r:
        assert "text/event-stream" in r.headers.get("Content-Type")
        for line in r:
            if line.startswith(b"data: "):
                events.append(json.loads(line[6:]))
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "start" and kinds[-1] == "end"
    assert {"task", "trace", "evidence", "hypotheses", "critique", "report"} <= set(kinds)
    report = next(e for e in events if e["kind"] == "report")
    run_id = report["run_id"]
    assert report["report"]["root_cause"]["service"] == "orders-db"
    sc = get_json(f"{base}/api/runs/{run_id}/score")
    assert sc["score"]["correct"] is True
    assert any(r["run_id"] == run_id for r in get_json(f"{base}/api/runs"))


def test_eval_results_served(base):
    sets = get_json(f"{base}/api/eval")
    assert "offline" in sets
    d = get_json(f"{base}/api/eval/offline")
    assert set(d["summary"]) == {"multi", "single"}
