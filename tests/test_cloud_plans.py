"""Plans, dollar billing through Dodo, older rupee subscriptions, AI metering and members' own keys in Propelo Cloud."""

import hashlib
import hmac
import json
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("cryptography")

SUB = {"id": "sub_TEST1234567890", "short_url": "https://rzp.io/i/abc123", "status": "created"}


@pytest.fixture(autouse=True)
def no_server_model(monkeypatch):
    for k in ("CAREEROS_LLM", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "OLLAMA_HOST", "CAREEROS_MODEL"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def fake_model(monkeypatch):
    from propelo import llm
    calls = []

    def complete(prompt, tier="default", system="", max_tokens=4096, json_mode=False, cfg=None, timeout=180, env=None):
        calls.append({"provider": cfg.provider if cfg else None, "base": cfg.base_url if cfg else None, "prompt": prompt})
        if "FAIL" in prompt:
            raise llm.LLMError("model down")
        return '{"ok": true}' if json_mode else "OK"
    monkeypatch.setattr(llm, "complete", complete)
    return calls


def _billing_on(cloud, posts):
    """Razorpay keys, as a server that takes rupee links from consultancies has them."""
    cloud.cfg.razorpay_key_id, cloud.cfg.razorpay_key_secret = "rzp_test_x", "secret"
    cloud.cfg.razorpay_webhook_secret = "whsec"

    def post(url, body, kid, ksec):
        posts.append((url, body, kid))
        return {"id": SUB["id"], "status": "active"}
    cloud.app.state.razorpay.post = post


def _older_rupee_subscription(cloud, uid, sub_id=None, plan="pro"):
    """A rupee subscription started before members moved to dollars."""
    from propelo.cloud import plans
    with cloud.db.tx() as t:
        plans.start_checkout(t, uid, {"id": sub_id or SUB["id"], "status": "created"}, plan, "razorpay", "INR")


def _pro(cloud, email="asha@example.com", until=None):
    """Grant Pro directly, as an operator would."""
    from propelo.cloud import plans
    with cloud.db.tx() as t:
        uid = t.one("SELECT id FROM users WHERE email = ?", (email,))["id"]
        plans.grant(t, uid, "test", until)


def _hook(cloud, event, eid="evt_1", secret="whsec"):
    body = json.dumps(event).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return cloud.client().post("/api/billing/webhook", content=body,
                               headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": eid})


def _sub_event(kind, status, end=None, at=None, sub_id=None, notes=None):
    ent = {"id": sub_id or SUB["id"], "status": status, "current_end": end or int(time.time()) + 30 * 86400}
    if notes:
        ent["notes"] = notes
    return {"event": kind, "created_at": at or int(time.time()), "payload": {"subscription": {"entity": ent}}}


def test_new_accounts_are_free_and_see_the_catalog(cloud):
    c = cloud.user()
    me = c.get("/api/me").json()
    assert me["plan"] == "free" and me["ai"]["source"] == "none" and me["ai"]["available"] is False
    cat = cloud.client().get("/api/plans").json()
    assert [p["id"] for p in cat["plans"]] == ["free", "pro", "ultra"] and cat["plans"][1]["priceUsd"] == "39.00"
    assert cat["checkoutEnabled"] is False and cat["currency"] == "USD"
    assert c.post("/api/billing/checkout").status_code == 503


def test_hosted_ai_is_metered_by_plan(cloud, monkeypatch, fake_model):
    monkeypatch.setenv("CAREEROS_LLM", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-server-key-0000")
    cloud.cfg.free_ai_credits = 2
    c = cloud.user()
    assert c.get("/api/me").json()["ai"] == pytest.approx(c.get("/api/me").json()["ai"])
    assert c.get("/api/me").json()["ai"]["source"] == "hosted"
    assert c.post("/api/ai", json={"prompt": "hi", "json": True}).json() == {"json": {"ok": True}, "source": "hosted"}
    assert c.post("/api/ai", json={"prompt": "FAIL"}).status_code == 502  # a failed call isn't counted
    assert c.post("/api/ai", json={"prompt": "hi"}).json()["text"] == "OK"
    r = c.post("/api/ai", json={"prompt": "hi"})
    assert r.status_code == 402 and r.json()["code"] == "ai_quota" and "Pro and Ultra include more" in r.json()["error"]
    assert c.get("/api/billing").json()["ai"]["left"] == 0
    # computer keys can't spend AI
    k = cloud.client()
    k.headers["Authorization"] = "Bearer " + c.post("/api/tokens", json={"name": "pc"}).json()["key"]
    assert k.post("/api/ai", json={"prompt": "hi"}).status_code == 403


def test_own_key_is_for_pro_and_ultra(cloud, fake_model):
    c = cloud.user()
    key = "sk-proj-abcdefghijklmnopqrstuvwxyz1234"
    r = c.put("/api/me/ai-key", json={"provider": "openai", "key": key})
    assert r.status_code == 402 and r.json()["code"] == "plan_limit" and "Pro and Ultra" in r.json()["error"]
    assert c.get("/api/billing").json()["ai"]["ownKeyAllowed"] is False
    _pro(cloud)
    assert c.put("/api/me/ai-key", json={"provider": "openai", "key": key}).status_code == 200
    assert c.post("/api/ai", json={"prompt": "hi"}).json()["source"] == "own"
    # Back on Free, a saved key stays saved but isn't used.
    _pro(cloud, until="2000-01-01T00:00:00Z")
    me = c.get("/api/me").json()
    assert me["plan"] == "free" and me["ai"]["source"] == "none" and me["ai"]["ownKey"]["hint"] == "…1234"
    assert c.post("/api/ai", json={"prompt": "hi"}).status_code == 503


def test_own_key_is_encrypted_and_unmetered(cloud, fake_model):
    c = cloud.user()
    _pro(cloud)
    key = "sk-proj-abcdefghijklmnopqrstuvwxyz1234"
    r = c.put("/api/me/ai-key", json={"provider": "openai", "key": key, "baseUrl": "https://openrouter.ai/api/v1"})
    assert r.status_code == 200 and r.json()["ownKey"]["hint"] == "…1234"
    with cloud.db.tx() as t:
        stored = t.one("SELECT secret FROM ai_keys")["secret"]
    assert key not in stored and "abcdefgh" not in stored
    assert key not in json.dumps(c.get("/api/billing").json()) and key not in c.get("/api/me/export").text
    cloud.cfg.pro_ai_credits = 0
    for _ in range(3):
        assert c.post("/api/ai", json={"prompt": "hi"}).json()["source"] == "own"
    assert fake_model[-1]["provider"] == "openai" and fake_model[-1]["base"] == "https://openrouter.ai/api/v1"
    assert c.get("/api/billing").json()["ai"]["ownUsed"] == 3
    assert c.post("/api/me/ai-key/test").json()["ok"] is True
    # another account never uses it
    b = cloud.user("bala@example.com")
    assert b.post("/api/ai", json={"prompt": "hi"}).status_code == 503
    assert c.delete("/api/me/ai-key").status_code == 200 and c.get("/api/me").json()["ai"]["ownKey"] is None


@pytest.mark.parametrize("body", [
    {"provider": "openai", "key": "sk-proj-abcdefghijklmnop", "baseUrl": "http://169.254.169.254/latest"},
    {"provider": "openai", "key": "sk-proj-abcdefghijklmnop", "baseUrl": "https://evil.example.com/v1"},
    {"provider": "openai", "key": "sk-proj-abcdefghijklmnop", "baseUrl": "https://api.openai.com:8443/v1"},
    {"provider": "anthropic", "key": "sk-ant-abcdefghijklmnop", "baseUrl": "https://api.openai.com/v1"},
    {"provider": "ollama", "key": "sk-abcdefghijklmnopqrst"},
    {"provider": "openai", "key": "short"},
])
def test_own_key_rejects_unsafe_settings(cloud, body):
    c = cloud.user()
    _pro(cloud)
    assert c.put("/api/me/ai-key", json=body).status_code == 400


def test_members_pay_in_dollars_only(cloud):
    posts = []
    _billing_on(cloud, posts)
    c = cloud.user()
    for body in ({"plan": "pro", "currency": "INR"}, {"plan": "ultra", "currency": "GBP"}):
        r = c.post("/api/billing/checkout", json=body)
        assert r.status_code == 400 and r.json()["code"] == "bad_currency" and "US dollars" in r.json()["error"]
    assert c.post("/api/billing/pass", json={"currency": "INR"}).json()["code"] == "bad_currency"
    assert not posts and c.get("/api/billing").json()["currencies"] == []  # Razorpay alone sells nothing to members
    assert c.post("/api/billing/checkout", json={"plan": "pro"}).status_code == 503


def test_older_rupee_subscription_webhooks_and_cancel(cloud):
    posts = []
    _billing_on(cloud, posts)
    c = cloud.user()
    _older_rupee_subscription(cloud, c.uid)
    assert c.get("/api/me").json()["plan"] == "free"  # nothing paid yet

    assert _hook(cloud, _sub_event("subscription.activated", "active"), secret="wrong").status_code == 400
    assert _hook(cloud, _sub_event("subscription.activated", "active")).json()["result"] == "active"
    assert _hook(cloud, _sub_event("subscription.activated", "active")).json()["result"] == "duplicate"
    assert c.get("/api/me").json()["plan"] == "pro"
    assert _hook(cloud, {"event": "payment.captured", "payload": {}}, eid="evt_pay").json()["result"] == "ignored"

    v = c.post("/api/billing/cancel").json()
    assert posts[-1][0].endswith(f"/subscriptions/{SUB['id']}/cancel") and posts[-1][1] == {"cancel_at_cycle_end": 1}
    assert v["subscription"]["cancelAtPeriodEnd"] is True and v["plan"] == "pro"
    assert _hook(cloud, _sub_event("subscription.cancelled", "cancelled"), eid="evt_2").json()["result"] == "cancelled"
    assert c.get("/api/me").json()["plan"] == "pro"  # paid until the end of the cycle
    assert _hook(cloud, _sub_event("subscription.halted", "cancelled", end=int(time.time()) - 60), eid="evt_3").status_code == 200
    assert c.get("/api/me").json()["plan"] == "free"


def test_admin_grants_pro(cloud):
    admin, user = cloud.user("admin@example.com"), cloud.user("bala@example.com")
    assert user.post("/api/admin/grant", json={"email": "bala@example.com"}).status_code == 404
    assert admin.post("/api/admin/grant", json={"email": "bala@example.com", "until": "2099-01-01"}).json()["plan"] == "pro"
    assert user.get("/api/me").json()["plan"] == "pro"
    assert admin.post("/api/admin/grant", json={"email": "bala@example.com", "until": "2000-01-01"}).json()["plan"] == "free"
    assert admin.post("/api/admin/grant", json={"email": "bala@example.com", "until": "soon"}).status_code == 400
    assert "plans" in admin.get("/api/admin/overview").json()


def test_plan_caps_auto_apply_and_match_cadence(cloud):
    from propelo.cloud.db import now_iso
    from propelo.cloud.worker import Worker
    c = cloud.user()
    c.put("/api/d/settings/profile", json={"dailyCap": 20})
    k = cloud.client()
    k.headers["Authorization"] = "Bearer " + c.post("/api/tokens", json={"name": "pc"}).json()["key"]
    assert k.get("/api/agent/next").json()["dailyCap"] == 5
    from datetime import timedelta

    def matched(minutes_ago):
        with cloud.db.tx() as t:
            t.execute("DELETE FROM tasks")
            t.execute("DELETE FROM match_state")
            t.execute("INSERT INTO match_state(user_id, settings_hash, last_match_at, last_feed_at) VALUES (?, '', ?, ?)",
                      (c.uid, now_iso(timedelta(minutes=-minutes_ago)), now_iso()))

    def queued():
        with cloud.db.tx() as t:
            return t.scalar("SELECT COUNT(*) AS n FROM tasks WHERE kind = 'match_user' AND user_id = ?", (c.uid,))

    w = Worker(cloud.cfg, cloud.db, cloud.app.state.mailer, worker_id="w1")
    matched(70)
    w.queue_matches()
    assert queued() == 0  # Free: already matched today
    admin = cloud.user("admin@example.com")
    admin.post("/api/admin/grant", json={"email": "asha@example.com"})
    w.queue_matches()
    assert queued() == 1 and k.get("/api/agent/next").json()["dailyCap"] == 20  # Pro: hourly
    matched(20)
    w.queue_matches()
    assert queued() == 0
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "ultra"})
    w.queue_matches()
    assert queued() == 1 and k.get("/api/agent/next").json()["dailyCap"] == 20  # Ultra: every 15 minutes; own cap 20 < 60


def test_public_pages_and_installable_app(cloud):
    c = cloud.client()
    cloud.cfg.support_email = "help@example.com"
    for path, text in [("/pricing", "$39"), ("/refunds", "Refunds and cancellation"), ("/contact", "help@example.com"), ("/terms", "Terms of use")]:
        r = c.get(path)
        assert r.status_code == 200 and text in r.text, path
    assert "{{" not in c.get("/privacy").text
    m = c.get("/manifest.webmanifest")
    assert m.status_code == 200 and m.headers["content-type"].startswith("application/manifest+json") and m.json()["display"] == "standalone"
    sw = c.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"] and "caches" in sw.text
    assert c.get("/offline").status_code == 200 and "You're offline" in c.get("/offline").text
    assert c.get("/icons/icon-192.png").content.startswith(b"\x89PNG")
    assert c.get("/icons/../app.py").status_code == 404 and c.get("/icons/nope.png").status_code == 404
    assert c.get("/apple-touch-icon.png").status_code == 200
    csp = c.get("/login").headers["content-security-policy"]
    assert "manifest-src 'self'" in csp and "worker-src 'self'" in csp
    u = cloud.user()
    page = u.get("/").text
    assert 'rel="manifest"' in page and "serviceWorker" in page and 'class="dock"' in page


def test_webhooks_out_of_order_and_older_checkout_links(cloud):
    posts = []
    _billing_on(cloud, posts)
    c = cloud.user()
    _older_rupee_subscription(cloud, c.uid)
    now = int(time.time())
    assert _hook(cloud, _sub_event("subscription.cancelled", "cancelled", end=now - 10, at=now), eid="e1").json()["result"] == "cancelled"
    # an older "charged" event delivered late doesn't switch Pro back on
    assert _hook(cloud, _sub_event("subscription.charged", "active", at=now - 100), eid="e2").json()["result"] == "stale"
    assert c.get("/api/me").json()["plan"] == "free"
    # paying an earlier checkout link of the same account still gives Pro
    r = _hook(cloud, _sub_event("subscription.activated", "active", sub_id="sub_OLDLINK0000001", notes={"user_id": c.uid}, at=now + 5), eid="e3")
    assert r.json()["result"] == "active" and c.get("/api/me").json()["plan"] == "pro"
    # a signed event naming an account that doesn't exist changes nothing
    assert _hook(cloud, _sub_event("subscription.activated", "active", sub_id="sub_STRANGER000001", notes={"user_id": "nope"}), eid="e4").json()["result"] == "unknown"


# ---------------------------------------------------------------- 2.0: Ultra, dollars and Dodo Payments
import base64  # noqa: E402

DODO_SECRET = "whsec_" + base64.b64encode(b"dodo-test-secret-0123456789").decode()


def _dodo_on(cloud, calls):
    cloud.cfg.dodo_api_key, cloud.cfg.dodo_webhook_secret = "dodo_test_key", DODO_SECRET
    cloud.cfg.dodo_product_pro, cloud.cfg.dodo_product_ultra = "pdt_PRO", "pdt_ULTRA"

    def call(method, url, body, key):
        calls.append((method, url, body, key))
        if url.endswith("/checkouts"):
            return {"session_id": "cks_1", "checkout_url": "https://test.checkout.dodopayments.com/cks_1"}
        if "customer-portal" in url:
            return {"link": "https://test.customer.dodopayments.com/p/1"}
        return {"subscription_id": url.rsplit("/", 1)[-1]}
    cloud.app.state.dodo.call = call


def _dodo_hook(cloud, event, wid="msg_1", secret=DODO_SECRET, ts=None):
    body = json.dumps(event).encode()
    ts = str(ts or int(time.time()))
    key = base64.b64decode(secret[6:])
    sig = base64.b64encode(hmac.new(key, f"{wid}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    return cloud.client().post("/api/billing/dodo-webhook", content=body, headers={
        "Content-Type": "application/json", "webhook-id": wid, "webhook-timestamp": ts, "webhook-signature": f"v1,{sig}"})


def _dodo_event(kind, uid, sub="sub_dodo_1", product="pdt_ULTRA", at=None, **data):
    d = {"subscription_id": sub, "status": kind.split(".")[1], "product_id": product, "metadata": {"user_id": uid, "plan": "ultra"},
         "customer": {"customer_id": "cus_1", "email": "asha@example.com"}, "next_billing_date": "2099-01-01T00:00:00Z", **data}
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(at or time.time()))
    return {"business_id": "bus_1", "type": kind, "timestamp": stamp, "data": d}


def test_catalog_has_three_plans_priced_in_dollars(cloud):
    cat = cloud.client().get("/api/plans").json()
    free, pro, ultra = cat["plans"]
    assert (pro["priceUsd"], ultra["priceUsd"]) == ("39.00", "79.00") and "priceInr" not in pro and "featuresInr" not in pro
    assert any("400 AI actions" in f for f in pro["features"]) and any("own AI key" in f for f in pro["features"])
    assert (free["ownKey"], pro["ownKey"], ultra["ownKey"]) == (False, True, True)
    assert not any("own key" in f or "own AI key" in f for f in free["features"])
    assert [(x["plan"], x["priceUsd"]) for x in cat["passes"]["passes"]] == [("pro", "99.00"), ("ultra", "189.00")] and cat["passes"]["days"] == 90
    assert ultra["aiCredits"] == 1500 and ultra["autoApplyPerDay"] == 60 and ultra["matchEveryMinutes"] == 15
    assert ultra["copilotPerDay"] == 200 and ultra["mockInterviews"] == 60 and ultra["linkedinReview"] is True
    assert not any("nlimited copilot" in f for p in cat["plans"] for f in p["features"])
    assert cloud.client().get("/api/plans", headers={"CF-IPCountry": "US"}).json()["currency"] == "USD"
    # Dollars for everyone, India included: the checkout charges each buyer in their own currency.
    assert cloud.client().get("/api/plans", headers={"CF-IPCountry": "IN"}).json()["currency"] == "USD"
    assert cloud.client().get("/api/plans?currency=usd").json()["currency"] == "USD"


def test_standard_webhook_signature():
    from propelo.cloud import plans
    body, wid, ts = b'{"a":1}', "msg_x", "1700000000"
    key = base64.b64decode(DODO_SECRET[6:])
    sig = base64.b64encode(hmac.new(key, f"{wid}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    h = {"webhook-id": wid, "webhook-timestamp": ts, "webhook-signature": f"v1,bad v1,{sig}"}
    assert plans.verify_standard_webhook(body, h, DODO_SECRET, now=1700000100)
    assert not plans.verify_standard_webhook(body, h, DODO_SECRET, now=1700000000 + 301)  # too old
    assert not plans.verify_standard_webhook(body + b" ", h, DODO_SECRET, now=1700000100)
    assert not plans.verify_standard_webhook(body, dict(h, **{"webhook-id": "msg_y"}), DODO_SECRET, now=1700000100)
    assert not plans.verify_standard_webhook(body, h, "", now=1700000100)


def test_dollar_checkout_through_dodo(cloud):
    calls = []
    _dodo_on(cloud, calls)
    c = cloud.user()
    r = c.post("/api/billing/checkout", json={"plan": "ultra", "currency": "USD"})
    assert r.status_code == 200 and r.json()["url"].startswith("https://test.checkout.dodopayments.com/")
    method, url, body, key = calls[0]
    assert url == "https://test.dodopayments.com/checkouts" and body["product_cart"] == [{"product_id": "pdt_ULTRA", "quantity": 1}]
    assert body["metadata"] == {"user_id": c.uid, "plan": "ultra"} and key == "dodo_test_key"
    assert c.get("/api/me").json()["plan"] == "free"
    # Members can't pay in rupees
    assert c.post("/api/billing/checkout", json={"plan": "pro", "currency": "INR"}).status_code == 400

    assert _dodo_hook(cloud, _dodo_event("subscription.active", c.uid), secret="whsec_" + base64.b64encode(b"other").decode()).status_code == 400
    assert _dodo_hook(cloud, _dodo_event("subscription.active", c.uid)).json()["result"] == "active"
    assert _dodo_hook(cloud, _dodo_event("subscription.active", c.uid)).json()["result"] == "duplicate"
    me = c.get("/api/me").json()
    assert me["plan"] == "ultra"
    b = c.get("/api/billing").json()
    assert b["subscription"]["currency"] == "USD" and b["subscription"]["provider"] == "dodo" and b["subscription"]["portal"] is True
    assert c.post("/api/billing/portal").json()["url"].startswith("https://test.customer.dodopayments.com/")
    # an older event arriving late doesn't undo a newer one
    assert _dodo_hook(cloud, _dodo_event("subscription.on_hold", c.uid, at=time.time() - 3600), wid="msg_old").json()["result"] == "stale"
    assert c.post("/api/billing/checkout", json={"plan": "ultra", "currency": "USD"}).status_code == 409

    v = c.post("/api/billing/cancel").json()
    assert calls[-1][0] == "PATCH" and calls[-1][1].endswith("/subscriptions/sub_dodo_1") and calls[-1][2] == {"cancel_at_next_billing_date": True}
    assert v["subscription"]["cancelAtPeriodEnd"] is True and v["plan"] == "ultra"
    assert _dodo_hook(cloud, _dodo_event("subscription.expired", c.uid), wid="msg_exp").json()["result"] == "expired"
    assert c.get("/api/me").json()["plan"] == "free"


def test_dodo_ignores_events_for_unknown_accounts(cloud):
    _dodo_on(cloud, [])
    assert _dodo_hook(cloud, _dodo_event("subscription.active", "usr_nobody")).json()["result"] == "unknown"


def test_upgrade_keeps_pro_until_ultra_is_paid(cloud):
    calls = []
    _dodo_on(cloud, calls)
    c = cloud.user()
    assert c.post("/api/billing/checkout", json={"plan": "pro"}).status_code == 200
    ev = _dodo_event("subscription.active", c.uid, sub="sub_dodo_pro", product="pdt_PRO")
    ev["data"]["metadata"]["plan"] = "pro"
    assert _dodo_hook(cloud, ev).json()["result"] == "active"
    assert c.get("/api/me").json()["plan"] == "pro"

    r = c.post("/api/billing/checkout", json={"plan": "ultra"})
    assert r.status_code == 200 and calls[-1][2]["product_cart"] == [{"product_id": "pdt_ULTRA", "quantity": 1}]
    b = c.get("/api/billing").json()
    assert b["plan"] == "pro" and b["subscription"]["pendingPlan"] == "ultra"  # an abandoned checkout takes nothing away

    assert _dodo_hook(cloud, _dodo_event("subscription.active", c.uid, sub="sub_dodo_ultra"), wid="msg_ultra").json()["result"] == "active"
    b = c.get("/api/billing").json()
    assert b["plan"] == "ultra" and b["subscription"]["pendingPlan"] is None
    with cloud.db.tx() as t:
        task = t.one("SELECT kind, payload FROM tasks WHERE kind = 'billing_cancel'")
    assert json.loads(task["payload"]) == {"provider": "dodo", "sub_id": "sub_dodo_pro"}

    from propelo.cloud import plans
    from propelo.cloud.worker import cancel_superseded
    seen = []
    orig = plans._dodo_request
    plans._dodo_request = lambda method, url, body, key: (seen.append((method, url, body)), {})[1]
    try:
        cancel_superseded(cloud.cfg, json.loads(task["payload"]))
    finally:
        plans._dodo_request = orig
    assert seen == [("PATCH", "https://test.dodopayments.com/subscriptions/sub_dodo_pro", {"status": "cancelled"})]


def test_admin_can_grant_ultra(cloud):
    c = cloud.user()
    admin = cloud.user("admin@example.com")
    assert admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "ultra"}).json()["plan"] == "ultra"
    assert admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "gold"}).status_code == 400
    assert c.get("/api/me").json()["plan"] == "ultra"


def test_pricing_page_shows_dollars_only(cloud):
    c = cloud.client()
    for country in ("DE", "IN", "US"):
        r = c.get("/pricing", headers={"CF-IPCountry": country})
        assert "$39<small> / month</small>" in r.text and "$79<small> / month</small>" in r.text and "Ultra" in r.text
        assert "₹" not in r.text and "data-cur" not in r.text, country  # no rupee prices, no currency switch
        assert "pay in your own currency" in r.text
        assert "<script>" not in r.text  # nothing inline without a nonce


def test_pricing_page_offers_the_90_day_passes(cloud):
    c = cloud.client()
    page = c.get("/pricing").text
    assert "or $99 for 90 days, paid once." in page and "or $189 for 90 days, paid once." in page
    assert "Get the pass" not in page  # not on sale until the Dodo products are set
    _dodo_on(cloud, [])
    cloud.cfg.dodo_product_pass, cloud.cfg.dodo_product_pass_ultra = "pdt_PASS", "pdt_PASS_ULTRA"
    page = c.get("/pricing").text
    assert "buy%3Dpass-pro" in page and "buy%3Dpass-ultra" in page
    assert "Job Guarantee" not in page and "India" not in page
