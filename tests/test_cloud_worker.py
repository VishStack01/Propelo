"""The worker: feed ingestion (fail-closed), per-user matching and the durable task queue."""

import json
from datetime import timedelta

import pytest

pytest.importorskip("fastapi")

from conftest import feed_record, write_feed  # noqa: E402


def _worker(cloud, wid="w1"):
    from careeros.cloud.worker import Worker
    return Worker(cloud.cfg, cloud.db, cloud.app.state.mailer, worker_id=wid)


def test_ingest_then_match_each_user(cloud, tmp_path):
    from careeros.cloud.ingest import feed_state
    write_feed(tmp_path / "feed", [feed_record(i) for i in range(30)]
               + [feed_record(100, exp=3)]  # asks for 3 years: a near-miss
               + [feed_record(101, title="Sales Manager")])  # not a target role
    a = cloud.user("asha@example.com")
    b = cloud.user("bala@example.com")
    b.patch("/api/d/settings/profile", json={"titleExclude": ["Engineer 1"]})
    w = _worker(cloud)
    w.drain()
    with cloud.db.tx() as c:
        assert c.scalar("SELECT COUNT(*) AS n FROM jobs WHERE active = 1") == 32
        assert feed_state(c)["records"] == 32
    jobs_a = {d["id"]: d["data"] for d in a.get("/api/c/jobs").json()["docs"]}
    kept = [i for i, d in jobs_a.items() if d["stage"] == "found"]
    assert len(kept) == 30 and all(jobs_a[i]["checks"] for i in kept)
    assert jobs_a["co20-ai-engineer-100"]["stage"] == "skipped" and "Experience" in jobs_a["co20-ai-engineer-100"]["skip"]["gate"]
    assert "co21-ai-engineer-101" not in jobs_a
    jobs_b = {d["id"] for d in b.get("/api/c/jobs").json()["docs"]}
    assert len(jobs_b) < len(jobs_a)  # b's own filters
    run = [r["data"] for r in a.get("/api/c/runs").json()["docs"]][0]
    assert run["kind"] == "search" and run["added"] == 30 and "best remote-worldwide" in run["summary"]
    assert a.get("/api/d/settings/profile").json()["data"]["coverage"]["inventory"] == 32
    assert a.get("/api/me").json()["feed"]["inventory"] == 32
    # A second hourly run with no new feed changes nothing.
    with cloud.db.tx() as c:
        c.execute("UPDATE feed_state SET value = ? WHERE key = 'next_ingest_at'", ("2000-01-01T00:00:00Z",))
    w.drain()
    assert len(a.get("/api/c/jobs").json()["docs"]) == len(jobs_a)


def test_closed_roles_leave_the_pipeline_but_not_when_a_board_errored(cloud, tmp_path):
    records = [feed_record(i) for i in range(10)]
    write_feed(tmp_path / "feed", records)
    a = cloud.user()
    w = _worker(cloud)
    w.drain()
    a.patch("/api/d/jobs/co3-ai-engineer-3", json={"stage": "approved", "autoApply": "queued"})
    # Next scan: role 1 is gone (its board was read), role 2's board errored, role 3 is gone but the user queued it.
    write_feed(tmp_path / "feed", [r for r in records if r["id"] not in ("co1-ai-engineer-1", "co2-ai-engineer-2", "co3-ai-engineer-3")],
               generated="2099-01-01T00:00:00Z", errored=["Company 2"])
    from careeros.cloud.ingest import ingest
    assert ingest(cloud.db, cloud.cfg.feed_url, log=lambda *_: None)["closed"] == 2
    from careeros.cloud.matching import match_user
    match_user(cloud.db, a.uid, log=lambda *_: None)
    jobs = {d["id"]: d["data"] for d in a.get("/api/c/jobs").json()["docs"]}
    assert jobs["co1-ai-engineer-1"]["stage"] == "skipped" and jobs["co1-ai-engineer-1"]["skip"]["gate"] == "Closed"
    assert jobs["co2-ai-engineer-2"]["stage"] == "found"
    assert jobs["co3-ai-engineer-3"]["stage"] == "approved"  # your queue is yours


def test_ingest_fails_closed(cloud, tmp_path):
    from careeros.cloud.ingest import IngestError, ingest
    with pytest.raises(IngestError):
        ingest(cloud.db, str(tmp_path / "missing"), log=lambda *_: None)
    write_feed(tmp_path / "feed", [feed_record(i) for i in range(300)])
    ingest(cloud.db, cloud.cfg.feed_url, log=lambda *_: None)
    write_feed(tmp_path / "feed", [feed_record(i) for i in range(100)], generated="2099-01-01T00:00:00Z")
    with pytest.raises(IngestError, match="shrank"):
        ingest(cloud.db, cloud.cfg.feed_url, log=lambda *_: None)
    with cloud.db.tx() as c:
        assert c.scalar("SELECT COUNT(*) AS n FROM jobs WHERE active = 1") == 300
    assert ingest(cloud.db, cloud.cfg.feed_url, force=True, log=lambda *_: None)["closed"] == 200
    (tmp_path / "feed" / "summary.json").unlink()
    with pytest.raises(IngestError, match="summary"):
        ingest(cloud.db, cloud.cfg.feed_url, log=lambda *_: None)


def test_queue_dedupe_retry_and_leases(cloud):
    from careeros.cloud import repo
    from careeros.cloud.db import now_iso
    w1, w2 = _worker(cloud, "w1"), _worker(cloud, "w2")
    with cloud.db.tx() as c:
        c.execute("DELETE FROM tasks")
        c.execute("INSERT INTO feed_state(key, value, updated_at) VALUES ('next_ingest_at', '2999-01-01', 'x'), ('next_cleanup_at', '2999-01-01', 'x'), ('next_alerts_at', '2999-01-01', 'x')")
        assert repo.enqueue(c, "send_email", {"to": "a@example.com", "subject": "s", "text": "t"}, dedupe_key="mail:1")
        assert not repo.enqueue(c, "send_email", {"to": "a@example.com", "subject": "s", "text": "t"}, dedupe_key="mail:1")
        assert repo.enqueue(c, "nonsense", dedupe_key="bad", max_attempts=2)
    t = w1.claim()
    assert t["status"] == "running" and t["locked_by"] == "w1" and t["attempts"] == 1
    assert w2.claim()["kind"] != t["kind"]  # the second worker skips the leased task
    assert w2.claim() is None
    # w1 dies: once the lease runs out, another worker takes the task over.
    with cloud.db.tx() as c:
        c.execute("UPDATE tasks SET locked_until = ? WHERE id = ?", (now_iso(timedelta(minutes=-1)), t["id"]))
    again = w2.claim()
    assert again["id"] == t["id"] and again["locked_by"] == "w2" and again["attempts"] == 2
    w2.run(again)
    with cloud.db.tx() as c:
        rows = {r["kind"]: r for r in c.all("SELECT kind, status, payload, attempts, last_error, run_after FROM tasks")}
    assert rows["send_email"]["status"] == "done" and rows["send_email"]["payload"] == "{}"  # the link isn't kept
    assert rows["nonsense"]["status"] == "running"
    bad = [r for r in [w1.claim()] if r] or []
    with cloud.db.tx() as c:
        c.execute("UPDATE tasks SET locked_until = ?, status = 'running' WHERE kind = 'nonsense'", (now_iso(timedelta(minutes=-1)),))
    task = w1.claim()
    w1.run(task)
    with cloud.db.tx() as c:
        r = c.one("SELECT status, attempts, last_error FROM tasks WHERE kind = 'nonsense'")
    assert r["status"] == "failed" and "unknown task" in r["last_error"] and not bad
    with cloud.db.tx() as c:  # once finished, the same dedupe key can be queued again
        assert repo.enqueue(c, "send_email", {"to": "a@example.com", "subject": "s", "text": "t"}, dedupe_key="mail:1")


def test_failed_task_backs_off(cloud):
    from careeros.cloud import repo
    from careeros.cloud.db import now_iso
    w = _worker(cloud)
    with cloud.db.tx() as c:
        c.execute("DELETE FROM tasks")
        c.execute("INSERT INTO feed_state(key, value, updated_at) VALUES ('next_ingest_at', '2999-01-01', 'x'), ('next_cleanup_at', '2999-01-01', 'x'), ('next_alerts_at', '2999-01-01', 'x')")
        repo.enqueue(c, "ingest", dedupe_key="ingest", max_attempts=3)  # the feed folder doesn't exist: fails closed
    w.tick()
    with cloud.db.tx() as c:
        r = c.one("SELECT status, attempts, run_after, last_error FROM tasks WHERE kind = 'ingest'")
    assert r["status"] == "queued" and r["attempts"] == 1 and r["run_after"] > now_iso(timedelta(minutes=1)) and "empty" in r["last_error"]
    assert w.claim() is None  # not due yet


def test_scheduler_and_cleanup(cloud):
    from careeros.cloud.worker import cleanup
    w = _worker(cloud)
    with cloud.db.tx() as c:
        c.execute("DELETE FROM tasks")
    w.schedule()
    w.schedule()
    with cloud.db.tx() as c:
        kinds = sorted(r["kind"] for r in c.all("SELECT kind FROM tasks"))
    assert kinds == ["alerts", "cleanup", "ingest"]  # once each, however often the scheduler ticks
    out = cleanup(cloud.db)
    assert set(out) == {"sessions", "links", "rate", "tasks", "jobs", "audit"}
    assert json.dumps(out)


def test_concurrent_workers_claim_each_task_once(cloud):
    import threading

    from careeros.cloud import repo
    with cloud.db.tx() as c:
        c.execute("DELETE FROM tasks")
        c.execute("INSERT INTO feed_state(key, value, updated_at) VALUES ('next_ingest_at', '2999-01-01', 'x'), ('next_cleanup_at', '2999-01-01', 'x'), ('next_alerts_at', '2999-01-01', 'x')")
        for i in range(60):
            repo.enqueue(c, "cleanup", dedupe_key=f"t{i}")
    claimed, lock = [], threading.Lock()

    def work(wid):
        w = _worker(cloud, wid)
        while True:
            t = w.claim()
            if not t:
                return
            with lock:
                claimed.append(t["id"])
    threads = [threading.Thread(target=work, args=(f"w{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(claimed) == 60 and len(set(claimed)) == 60


def test_ingest_drops_implausible_pay(cloud, tmp_path):
    import json as _json

    from careeros.cloud.ingest import ingest
    r = feed_record(1)
    r["facts"].update(salaryLow=687280.0, salaryHigh=687280.0, salaryQuote="We've raised $781M")
    write_feed(tmp_path / "feed", [r, feed_record(2)])
    ingest(cloud.db, cloud.cfg.feed_url, log=lambda *_: None)
    with cloud.db.tx() as c:
        facts = {row["id"]: _json.loads(row["record"])["facts"] for row in c.all("SELECT id, record FROM jobs")}
    assert "salaryHigh" not in facts[r["id"]] and facts[feed_record(2)["id"]]["salaryHigh"] == 14.0


def test_job_alerts_are_opt_in_and_only_for_new_roles(cloud):
    from datetime import datetime, timedelta, timezone
    from careeros.cloud import alerts, repo
    c = cloud.user()
    now = datetime.now(timezone.utc)
    stamp = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for i in range(3):
        c.put(f"/api/d/jobs/j{i}", json={"company": f"Co {i}", "title": "Data Analyst", "url": f"https://jobs.example.com/{i}", "stage": "found", "foundAt": stamp})
    c.put("/api/d/jobs/mine", json={"company": "Mine", "title": "PM", "url": "https://x.example/1", "stage": "approved", "manual": True, "foundAt": stamp})
    with cloud.db.tx() as tx:
        before = tx.scalar("SELECT COUNT(*) FROM tasks WHERE kind = 'send_email'")
    assert alerts.send_due(cloud.db, "https://propelo.in", now=now, log=lambda *_: None) == 0  # off by default
    c.patch("/api/d/settings/profile", json={"alerts": "daily"})
    assert alerts.send_due(cloud.db, "https://propelo.in", now=now, log=lambda *_: None) == 1
    with cloud.db.tx() as tx:
        row = tx.one("SELECT payload FROM tasks WHERE kind = 'send_email' ORDER BY created_at DESC LIMIT 1")
        assert tx.scalar("SELECT COUNT(*) FROM tasks WHERE kind = 'send_email'") == before + 1
    body = __import__("json").loads(row["payload"])
    assert body["subject"] == "3 new roles for you on Propelo" and "https://jobs.example.com/0" in body["text"]
    assert "Mine" not in body["text"] and "Turn them off in Settings" in body["text"]
    # Not again until the next period, and nothing when nothing is new
    assert alerts.send_due(cloud.db, "https://propelo.in", now=now + timedelta(hours=1), log=lambda *_: None) == 0
    assert alerts.send_due(cloud.db, "https://propelo.in", now=now + timedelta(days=1), log=lambda *_: None) == 0


def _match(cloud, uid):
    from careeros.cloud.matching import match_user
    return match_user(cloud.db, uid, log=lambda *_: None)


def _ingest(cloud, tmp_path, records, generated):
    from careeros.cloud.ingest import ingest
    write_feed(tmp_path / "feed", records, generated=generated)
    return ingest(cloud.db, cloud.cfg.feed_url, log=lambda *_: None)


def test_a_repeat_match_reads_only_what_changed(cloud, tmp_path):
    records = [feed_record(i) for i in range(20)]
    _ingest(cloud, tmp_path, records, "2099-01-01T00:00:00Z")
    a = cloud.user()
    first = _match(cloud, a.uid)
    assert first["full"] and first["read"] == 20 and first["added"] == 20
    # Nothing new: a changed-roles pass (it still looks a few hours back, so it re-reads what was just taken in
    # and recognises it), and no role is taken for closed just because it was not read again.
    again = _match(cloud, a.uid)
    assert not again["full"] and again["added"] == 0 and again["closed"] == 0
    with cloud.db.tx() as c:
        c.execute("UPDATE jobs SET last_seen_at = '2020-01-01T00:00:00.000000Z'")   # as if taken in long ago
    assert _match(cloud, a.uid)["read"] == 0
    # A new scan: two new roles, one closed, one whose posting changed.
    changed = dict(records[5], summary="We build AI agents with Python. Freshers welcome. Updated.")
    nxt = [r for r in records if r["id"] not in (records[4]["id"], records[5]["id"])] + [changed, feed_record(50), feed_record(51)]
    res = _ingest(cloud, tmp_path, nxt, "2099-01-02T00:00:00Z")
    assert res["closed"] == 1
    third = _match(cloud, a.uid)
    assert not third["full"] and third["read"] == 3            # the two new roles and the changed one, not all 21
    assert third["added"] == 2 and third["closed"] == 1
    jobs = {d["id"]: d["data"] for d in a.get("/api/c/jobs").json()["docs"]}
    assert jobs[records[4]["id"]]["skip"]["gate"] == "Closed" and jobs[records[0]["id"]]["stage"] == "found"
    assert jobs["co10-ai-engineer-50"]["stage"] == "found"


def test_everything_is_read_again_when_it_has_to_be(cloud, tmp_path):
    from careeros.cloud.db import now_iso
    records = [feed_record(i) for i in range(12)] + [feed_record(90, title="Data Analyst")]
    _ingest(cloud, tmp_path, records, "2099-01-01T00:00:00Z")
    a = cloud.user()
    assert _match(cloud, a.uid)["full"] and not _match(cloud, a.uid)["full"]
    # Any filter that decides a match: the sponsorship switch was once left out of the settings hash.
    a.patch("/api/d/settings/profile", json={"needsSponsorship": True})
    assert _match(cloud, a.uid)["full"]
    a.patch("/api/d/settings/profile", json={"targetRoles": ["Data Analyst"]})
    r = _match(cloud, a.uid)
    assert r["full"] and r["added"] == 1                        # the old role now fits and is found
    assert not _match(cloud, a.uid)["full"]
    a.patch("/api/d/settings/profile", json={"note": "not a filter"})
    assert not _match(cloud, a.uid)["full"]
    # Once a week, whatever else is true.
    with cloud.db.tx() as c:
        c.execute("UPDATE match_state SET full_at = ? WHERE user_id = ?", (now_iso(-timedelta(days=8)), a.uid))
    assert _match(cloud, a.uid)["full"] and not _match(cloud, a.uid)["full"]


def test_more_fits_than_one_run_adds_means_another_full_pass(cloud, tmp_path):
    from careeros.cloud import matching
    _ingest(cloud, tmp_path, [feed_record(i, company=f"Co {i}") for i in range(170)], "2099-01-01T00:00:00Z")
    a = cloud.user()
    r1 = _match(cloud, a.uid)
    assert r1["added"] == 150                                   # one run adds at most 150
    r2 = _match(cloud, a.uid)
    assert r2["full"] and r2["added"] == 20                     # the rest arrive on the next run, as before
    assert not _match(cloud, a.uid)["full"]
    # Roles are read in pages and never all held at once; paging neither drops nor repeats one.
    got = list(matching._records(cloud.db, "", page=50))
    assert [r["title"] for r in matching._records(cloud.db, "", lambda t: t.endswith(" 7"), page=50)] == ["AI Engineer 7"]
    assert len(got) == 170 and len({r["id"] for r in got}) == 170
    assert len(list(matching._urls(cloud.db, page=7))) == 170


def test_changing_filters_takes_back_untouched_roles_that_no_longer_fit(cloud, tmp_path):
    records = [feed_record(i) for i in range(8)] + [feed_record(20 + i, title=f"Data Analyst {i}", company=f"Data Co {i}") for i in range(3)]
    _ingest(cloud, tmp_path, records, "2099-01-01T00:00:00Z")
    a = cloud.user()
    assert _match(cloud, a.uid)["added"] == 8                    # the starting filters: engineering roles
    a.patch("/api/d/jobs/co1-ai-engineer-1", json={"saved": True})
    a.patch("/api/d/jobs/co2-ai-engineer-2", json={"stage": "approved"})
    a.patch("/api/d/jobs/co3-ai-engineer-3", json={"notes": "ask Priya about this team"})
    a.patch("/api/d/settings/profile", json={"targetRoles": ["Data Analyst"]})
    r = _match(cloud, a.uid)
    assert r["full"] and r["added"] == 3 and r["removed"] == 5   # the five nobody touched leave; the three acted on stay
    jobs = {d["id"]: d["data"] for d in a.get("/api/c/jobs").json()["docs"]}
    assert {"co1-ai-engineer-1", "co2-ai-engineer-2", "co3-ai-engineer-3"} <= set(jobs) and "co0-ai-engineer-0" not in jobs
    assert sum(1 for d in jobs.values() if d["title"].startswith("Data Analyst")) == 3
    # The same filters again: nothing is judged twice, nothing is removed.
    r = _match(cloud, a.uid)
    assert not r["full"] and r["removed"] == 0 and len(a.get("/api/c/jobs").json()["docs"]) == len(jobs)
    # A wider filter keeps what still fits.
    a.patch("/api/d/settings/profile", json={"targetRoles": ["Data Analyst", "AI Engineer"]})
    r = _match(cloud, a.uid)
    assert r["removed"] == 0 and r["added"] == 5


def test_filters_saved_during_a_match_are_matched_straight_after(cloud, tmp_path, monkeypatch):
    from careeros import feed
    from careeros.cloud import matching
    _ingest(cloud, tmp_path, [feed_record(i) for i in range(4)] + [feed_record(30, title="Data Analyst")], "2099-01-01T00:00:00Z")
    a = cloud.user()
    real = feed.match

    def slow(*args, **kw):                                       # the person answers the first questions while this run reads
        out = real(*args, **kw)
        a.patch("/api/d/settings/profile", json={"targetRoles": ["Data Analyst"]})
        return out
    monkeypatch.setattr(matching.feed, "match", slow)
    w = _worker(cloud)
    w.drain()
    monkeypatch.setattr(matching.feed, "match", real)
    with cloud.db.tx() as c:
        c.execute("UPDATE tasks SET run_after = '2000-01-01T00:00:00.000000Z' WHERE status = 'queued'")
    w.drain()
    titles = sorted(d["data"]["title"] for d in a.get("/api/c/jobs").json()["docs"] if d["data"].get("stage") == "found")
    assert titles == ["Data Analyst"]


def test_a_long_skip_list_never_blocks_new_matches(cloud, tmp_path, monkeypatch):
    from careeros.cloud import matching
    monkeypatch.setattr(matching, "MAX_SKIPPED", 3)
    near = [feed_record(200 + i, exp=3, company=f"Near {i}") for i in range(10)]            # ask for 3 years: near misses
    _ingest(cloud, tmp_path, near + [feed_record(1)], "2099-01-01T00:00:00Z")
    a = cloud.user()
    r = _match(cloud, a.uid)
    assert r["added"] == 1 and r["skipped"] == 3                                             # the skip list stops at its own limit
    _ingest(cloud, tmp_path, near + [feed_record(1), feed_record(2), feed_record(3)], "2099-01-02T00:00:00Z")
    r = _match(cloud, a.uid)
    assert r["added"] == 2 and r["skipped"] == 0                                             # and new matches still arrive
