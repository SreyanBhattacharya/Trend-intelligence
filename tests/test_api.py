"""Dashboard API against a real Postgres (set TEST_DATABASE_URL)."""
import time

import pytest

from tests.test_integration import _demo_posts_at_peak


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient

    from api.server import app

    return TestClient(app)


@pytest.fixture
def seeded(client):
    from agents.data_collection_agent import DataCollectionAgent
    from workflows.pipeline import recorded_run, run_pipeline

    posts, topic = _demo_posts_at_peak()
    with recorded_run("collect:all", "test") as out:
        out["demo"] = DataCollectionAgent()._store("demo", posts)
    run_pipeline(trigger="test")
    return topic


def test_index_and_health(client):
    r = client.get("/")
    assert r.status_code == 200 and "Trend Intel" in r.text
    assert client.get("/api/health").json()["database"] is True


def test_empty_database_endpoints(client):
    ov = client.get("/api/overview").json()
    assert ov["counts"]["posts_total"] == 0 and ov["demo_mode"] is True
    for path in ("/api/trends", "/api/alerts", "/api/ideas", "/api/runs", "/api/keywords"):
        assert client.get(path).json() == [], path
    assert len(client.get("/api/activity?hours=6").json()) == 6
    assert client.get("/api/posts").json() == {"total": 0, "items": []}
    assert client.get("/api/trends/999").status_code == 404


def test_dashboard_data_after_pipeline(client, seeded):
    topic = seeded
    ov = client.get("/api/overview").json()
    assert ov["counts"]["trends_active"] >= 1 and ov["counts"]["alerts_24h"] >= 1
    assert {m["platform"] for m in ov["platform_mix"]} == {"reddit", "twitter", "youtube"}

    trends = client.get("/api/trends").json()
    top = next(t for t in trends if t["trend_name"] == topic)
    assert top["virality_probability"] >= 70 and len(top["series"]) == 27
    assert set(top["platform_split"]) == {"reddit", "twitter", "youtube"}
    assert top["idea"]["hook"] and top["alert_count"] == 1

    detail = client.get(f"/api/trends/{top['id']}").json()
    assert detail["posts"] and detail["alerts"] and detail["ideas"] and len(detail["series"]) == 27

    posts = client.get("/api/posts", params={"q": topic, "limit": 5}).json()
    assert posts["total"] > 0 and all(topic in p["text"].lower() for p in posts["items"])
    assert posts["items"][0]["keywords"][0] == topic  # most specific phrase first
    assert client.get("/api/posts", params={"platform": "youtube", "limit": 3}).json()["items"][0]["platform"] == "youtube"

    kws = [k["word"] for k in client.get("/api/keywords").json()]
    assert topic not in kws and topic.replace(" ", "") not in kws  # active trends are excluded

    runs = client.get("/api/runs").json()
    assert [r["task"] for r in runs] == ["pipeline", "collect:all"]
    assert runs[0]["status"] == "success" and runs[0]["summary"]["alerts_sent"] >= 1

    alerts = client.get("/api/alerts").json()
    assert alerts[0]["trend_name"] and alerts[0]["virality_at_alert"] >= 70
    assert client.get("/api/ideas").json()[0]["trend_name"]
    assert client.get("/api/config").json()["schedule"]


def test_run_endpoint(client):
    assert client.post("/api/run", json={"task": "nope"}).status_code == 400
    assert client.post("/api/run", json={"task": "all"}).status_code == 202
    for _ in range(100):
        if not client.get("/api/run").json()["running"]:
            break
        time.sleep(0.2)
    tasks = {r["task"]: r for r in client.get("/api/runs").json()}
    assert tasks["pipeline"]["trigger"] == "dashboard" and tasks["pipeline"]["status"] == "success"
    assert tasks["collect:all"]["summary"]["demo"] > 0
