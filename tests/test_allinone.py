"""One-server mode (ALL_IN_ONE=on) and uploads kept in the database (STORAGE=db): what a free host needs."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from conftest import make_pdf

ROOT = Path(__file__).resolve().parent.parent


def test_settings_from_the_environment(monkeypatch):
    from careeros.cloud.config import Config
    for k in ("PUBLIC_URL", "RENDER_EXTERNAL_URL", "STORAGE", "ALL_IN_ONE"):
        monkeypatch.delenv(k, raising=False)
    cfg = Config.from_env()
    assert cfg.public_url == "http://127.0.0.1:8000" and cfg.storage == "disk" and cfg.all_in_one is False
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://propelo.onrender.com/")
    monkeypatch.setenv("PUBLIC_URL", "")           # a blank value in the host's dashboard is not an address
    monkeypatch.setenv("STORAGE", "DB")
    monkeypatch.setenv("ALL_IN_ONE", "on")
    cfg = Config.from_env()
    assert cfg.public_url == "https://propelo.onrender.com" and cfg.storage == "db" and cfg.all_in_one is True
    monkeypatch.setenv("PUBLIC_URL", "https://app.propelo.org")
    assert Config.from_env().public_url == "https://app.propelo.org"   # the real domain wins once it is set


def test_unknown_storage_is_refused_in_production():
    from careeros.cloud.config import Config
    cfg = Config(app_env="production", database_url="postgresql://u:p@h/d", public_url="https://x.example", smtp_url="smtps://u:p@h:465",
                 secrets_key="k" * 40, storage="bucket")
    assert cfg.check() == ["STORAGE must be disk or db."]
    cfg.storage = "db"
    assert cfg.check() == []


def test_uploads_live_in_the_database(cloud, tmp_path):
    from careeros.cloud.storage import DbStorage, LocalStorage, make_storage
    assert isinstance(make_storage(cloud.cfg, cloud.db), LocalStorage)
    cloud.cfg.storage = "db"
    store = make_storage(cloud.cfg, cloud.db)
    assert isinstance(store, DbStorage)
    cloud.app.state.storage = store
    uid, aid = "a" * 32, "b" * 32
    key = store.put(uid, aid, "pdf", b"%PDF-1.4 one")
    assert key == f"{uid}/{aid}.pdf" and store.get(key) == b"%PDF-1.4 one"
    assert store.put(uid, aid, "pdf", b"%PDF-1.4 two") == key and store.get(key) == b"%PDF-1.4 two"   # replaced, not doubled
    with cloud.db.tx() as c:
        assert c.scalar("SELECT COUNT(*) AS n FROM blobs") == 1
    store.put(uid, "c" * 32, "pdf", b"x")
    store.delete(key)
    with pytest.raises(FileNotFoundError):
        store.get(key)
    store.delete(key)                                # deleting twice is fine
    store.delete_user(uid)
    with cloud.db.tx() as c:
        assert c.scalar("SELECT COUNT(*) AS n FROM blobs") == 0
    for bad in ("../etc/passwd", "x/y.pdf", f"{uid}/{aid}.pdf/../z"):
        with pytest.raises(ValueError):
            store.get(bad)
    with pytest.raises(ValueError):
        store.put("../x", aid, "pdf", b"x")
    assert not list((tmp_path / "uploads").rglob("*.pdf"))   # nothing was written to the disk


def test_the_app_serves_uploads_from_the_database(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from careeros.cloud.app import create_app
    from careeros.cloud.config import Config
    from careeros.cloud.mailer import OUTBOX
    import re

    cfg = Config(database_url=f"sqlite:///{tmp_path}/c.db", upload_dir=tmp_path / "uploads", storage="db", password_iterations=1000,
                 public_url="http://testserver", feed_url=str(tmp_path / "feed"))
    app = create_app(cfg)
    try:
        def member(email):
            c = TestClient(app)
            c.headers["X-CareerOS-CSRF"] = "1"
            assert c.post("/api/auth/signup", json={"email": email, "password": "correct horse battery", "name": "A"}).status_code == 202
            token = re.search(r"/verify#token=([\w-]+)", OUTBOX[-1]["text"]).group(1)
            assert c.post("/api/auth/verify", json={"token": token}).status_code == 200
            return c
        a, b = member("asha@example.com"), member("bala@example.com")
        pdf = make_pdf("Asha Example Python FastAPI")
        r = a.post("/api/assets?name=cv.pdf", content=pdf, headers={"Content-Type": "application/pdf"})
        assert r.status_code == 201, r.text
        aid = r.json()["id"]
        assert a.get(f"/_blob/{aid}").content == pdf
        assert b.get(f"/_blob/{aid}").status_code == 404                     # still owner-only
        assert not list((tmp_path / "uploads").rglob("*.pdf"))
        with app.state.db.tx() as c:
            c.execute("DELETE FROM blobs")                                     # the row is gone but the listing still names it
        assert a.get(f"/_blob/{aid}").status_code == 404
        r2 = a.post("/api/assets?name=cv2.pdf", content=pdf, headers={"Content-Type": "application/pdf"}).json()["id"]
        assert a.delete(f"/api/assets/{r2}").status_code == 200
        with app.state.db.tx() as c:
            assert c.scalar("SELECT COUNT(*) AS n FROM blobs") == 0
    finally:
        app.state.db.close()


def test_prepare_migrates_and_refuses_unsafe_settings(tmp_path, capsys):
    from careeros.cloud.allinone import prepare
    from careeros.cloud.config import Config
    db = prepare(Config(database_url=f"sqlite:///{tmp_path}/one.db"))
    try:
        assert db.pending_migrations() == []
        with db.tx() as c:
            assert c.scalar("SELECT COUNT(*) AS n FROM blobs") == 0
    finally:
        db.close()
    assert "migration(s) applied" in capsys.readouterr().out
    prepare(Config(database_url=f"sqlite:///{tmp_path}/one.db")).close()
    assert "Database is up to date." in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        prepare(Config(app_env="production", database_url=f"sqlite:///{tmp_path}/two.db"))
    assert "Unsafe configuration" in str(e.value) and not (tmp_path / "two.db").exists()   # nothing is touched first


def _wait(cond, seconds=10.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_the_worker_child_is_restarted_and_stopped():
    from careeros.cloud.allinone import WorkerChild
    quick = WorkerChild([sys.executable, "-c", "raise SystemExit(3)"], base_delay=0.05)
    quick.start()
    assert _wait(lambda: quick.starts >= 3)          # it keeps coming back after a failure
    quick.close()
    n = quick.starts
    time.sleep(0.5)
    assert quick.starts == n                          # and stays stopped once closed

    slow = WorkerChild([sys.executable, "-c", "import time; time.sleep(120)"], base_delay=0.05)
    slow.start()
    assert _wait(lambda: slow.proc is not None and slow.proc.poll() is None)
    t = time.monotonic()
    slow.close()
    assert slow.proc.poll() is not None and time.monotonic() - t < 8 and slow.starts == 1

    missing = WorkerChild(["/no/such/program"], base_delay=0.05)
    missing.start()
    time.sleep(0.2)
    missing.close()                                   # a missing program neither raises nor spins
    assert missing.starts == 0


def test_the_free_blueprint_is_one_free_service():
    yaml = pytest.importorskip("yaml")
    d = yaml.safe_load((ROOT / "render.free.yaml").read_text())
    assert [x["plan"] for x in d["databases"]] == ["free"]
    (web,) = d["services"]                            # no worker service: workers are not free
    assert web["type"] == "web" and web["plan"] == "free" and web["runtime"] == "docker"
    assert "disk" not in web and "preDeployCommand" not in web   # neither exists on a free instance
    env = {e["key"]: e for e in web["envVars"]}
    assert env["ALL_IN_ONE"]["value"] == "on" and env["STORAGE"]["value"] == "db" and env["APP_ENV"]["value"] == "production"
    assert env["DATABASE_URL"]["fromDatabase"]["name"] == d["databases"][0]["name"]
    assert env["SECRETS_KEY"] == {"key": "SECRETS_KEY", "generateValue": True}
    assert "PUBLIC_URL" not in env                    # the app reads the address Render gives the service
    for secret in ("SMTP_URL", "MAIL_FROM", "SUPPORT_EMAIL", "BOOTSTRAP_ADMIN_EMAIL"):
        assert env[secret] == {"key": secret, "sync": False}   # typed into Render by the owner, never stored here


def test_the_image_listens_on_the_port_the_host_names():
    text = (ROOT / "Dockerfile").read_text()
    assert "--port ${PORT:-8000}" in text and "exec careeros cloud serve" in text


def test_replies_go_to_the_support_inbox():
    from careeros.cloud.mailer import OUTBOX, Mailer
    OUTBOX.clear()
    Mailer("console://", "Propelo <hello@propelo.org>", "help@example.com").send("a@example.com", "Hi", "Body")
    Mailer("console://", "Propelo <hello@propelo.org>").send("a@example.com", "Hi", "Body")
    Mailer("console://", "Propelo <hello@propelo.org>", "hello@propelo.org").send("a@example.com", "Hi", "Body")   # same inbox: no header
    Mailer("console://", "Propelo <hello@propelo.org>", "not an address").send("a@example.com", "Hi", "Body")
    assert [m["replyTo"] for m in OUTBOX] == ["help@example.com", "", "", ""]
