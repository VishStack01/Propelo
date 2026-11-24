"""Sign in with a mobile number: added and confirmed in Settings, then a texted code signs in."""

import pytest

pytest.importorskip("fastapi")

from propelo.cloud import phone


def test_numbers_are_normalised_or_refused():
    assert phone.normalize("+44 7700 900123") == "+447700900123"
    assert phone.normalize("0044 (7700) 900-123") == "+447700900123"
    assert phone.normalize("07700 900123") == ""  # no country code
    assert phone.normalize("+0 123 4567 89") == "" and phone.normalize("+1 23") == ""
    assert phone.mask("+447700900123") == "+44 ••• •••• 0123"


@pytest.fixture
def texts(cloud):
    for k, v in (("twilio_account_sid", "AC1"), ("twilio_auth_token", "tok"), ("twilio_verify_sid", "VA1")):
        object.__setattr__(cloud.cfg, k, v)
    sent, codes = [], {}

    def post(url, form, auth):
        if url.endswith("/Verifications"):
            sent.append(form["To"])
            codes[form["To"]] = "123456"
            return {"status": "pending"}
        return {"status": "approved" if codes.get(form["To"]) == form["Code"] else "pending"}
    cloud.app.state.phone.post = post
    return sent


def test_off_until_twilio_is_set_up(cloud):
    c = cloud.client()
    assert c.get("/api/auth/providers").json()["phone"] is False
    assert c.post("/api/auth/phone/start", json={"phone": "+447700900123"}).status_code == 404


def test_add_a_number_then_sign_in_with_it(cloud, texts):
    me = cloud.user()
    assert cloud.client().get("/api/auth/providers").json()["phone"] is True
    # A stranger's number never gets a text from the sign-in form, and the answer doesn't say whether it's known.
    stranger = cloud.client().post("/api/auth/phone/start", json={"phone": "+447700900999"})
    assert stranger.status_code == 202 and not texts
    # Add the number in Settings.
    assert me.post("/api/me/phone/start", json={"phone": "+44 7700 900123"}).status_code == 200 and texts == ["+447700900123"]
    assert me.post("/api/me/phone/verify", json={"phone": "+447700900123", "code": "000000"}).status_code == 400
    r = me.post("/api/me/phone/verify", json={"phone": "+447700900123", "code": "123456"})
    assert r.status_code == 200 and r.json()["phone"] == "+44 ••• •••• 0123"
    assert me.get("/api/me").json()["phone"] == "+44 ••• •••• 0123"
    # Sign in with it.
    c = cloud.client()
    assert c.post("/api/auth/phone/start", json={"phone": "+447700900123"}).status_code == 202 and len(texts) == 2
    assert c.post("/api/auth/phone/verify", json={"phone": "+447700900123", "code": "999999"}).status_code == 401
    r = c.post("/api/auth/phone/verify", json={"phone": "+447700900123", "code": "123456"})
    assert r.status_code == 200 and c.get("/api/me").json()["id"] == me.uid
    # The same number can't go on a second account.
    other = cloud.user("ravi@example.com")
    assert other.post("/api/me/phone/start", json={"phone": "+447700900123"}).json()["code"] == "phone_taken"
    # Removed, it no longer signs anyone in.
    assert me.delete("/api/me/phone").status_code == 200
    assert cloud.client().post("/api/auth/phone/verify", json={"phone": "+447700900123", "code": "123456"}).status_code == 401


def test_a_number_that_is_not_a_number_is_refused(cloud, texts):
    me = cloud.user()
    assert me.post("/api/me/phone/start", json={"phone": "07700 900123"}).json()["code"] == "bad_phone"
    assert not texts
