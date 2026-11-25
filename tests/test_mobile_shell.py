"""The phone apps' identity and permissions: one app id everywhere, a user agent the web app recognises."""

import json
import plistlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M = ROOT / "mobile"


def test_one_app_id_on_both_stores():
    cap = json.loads((M / "capacitor.config.json").read_text())
    gradle = (M / "android" / "app" / "build.gradle").read_text()
    pbx = (M / "ios" / "App" / "App.xcodeproj" / "project.pbxproj").read_text()
    assert cap["appId"] == "org.propelo.app"
    assert re.findall(r'applicationId "([^"]+)"', gradle) == ["org.propelo.app"] and 'namespace = "org.propelo.app"' in gradle
    assert set(re.findall(r"PRODUCT_BUNDLE_IDENTIFIER = ([^;]+);", pbx)) == {"org.propelo.app"}
    main = M / "android" / "app" / "src" / "main" / "java" / "org" / "propelo" / "app" / "MainActivity.java"
    assert main.read_text().startswith("package org.propelo.app;")
    assert not list((M / "android").rglob("*vishstack01*"))


def test_the_web_app_knows_it_is_inside_the_app():
    cap = json.loads((M / "capacitor.config.json").read_text())
    agents = [cap["android"]["appendUserAgent"], cap["ios"]["appendUserAgent"]]
    for name in ("dashboard/app.html", "propelo/cloud/static/auth.html"):
        rx = re.search(r"const inApp = /([^/]+)/\.test", (ROOT / name).read_text()).group(1)
        assert all(re.search(rx, a) for a in agents), name


def test_iphone_is_portrait_and_says_why_it_listens():
    info = plistlib.loads((M / "ios" / "App" / "App" / "Info.plist").read_bytes())
    assert info["UISupportedInterfaceOrientations"] == ["UIInterfaceOrientationPortrait"]
    assert "resume defence drill" in info["NSMicrophoneUsageDescription"] and "never a recording" in info["NSMicrophoneUsageDescription"]
    assert "NSSpeechRecognitionUsageDescription" in info
