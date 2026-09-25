"""เทสทั้งเส้นทาง: ออกรหัส → activate → ต่ออายุ → ระงับ → ย้ายเครื่อง → สั่งงานโพสต์

รันด้วย:  python -m pytest group-poster/tests -q
ไม่ต้องมีมือถือ — ตัวโพสต์จริงถูกแทนด้วยตัวปลอมที่ทำตามสัญญาของ post_to_groups
"""

from __future__ import annotations

import io
import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from agent import jobs as jobs_mod
from agent import main as agent_main
from agent.license_client import GRACE, LicenseClient
from common import license_format as lf
from server import admin
from server.license_server import create_app
from server.store import MAX_MOVES_PER_MONTH, Store

MACHINE_A = "a" * 40
MACHINE_B = "b" * 40


@pytest.fixture()
def store(tmp_path):
    return Store(tmp_path / "server")


@pytest.fixture()
def server(store):
    return TestClient(create_app(store))


def make_client(store, server, tmp_path, machine=MACHINE_A):
    config = {"server_url": "http://license", "public_key": store.public_key_text()}

    def http(method, url, json=None):
        return server.request(method, url.replace("http://license", ""), json=json)

    return LicenseClient(config, tmp_path / f"agent-{machine[:1]}", http=http, machine=machine)


# ---------------------------------------------------------------- รหัส

def test_code_format_and_normalize():
    code = lf.new_code()
    assert code.startswith("GP-") and len(code.split("-")) == 5
    assert lf.normalize_code(code.lower().replace("-", " ")) == code


def test_token_rejects_tampering(store):
    token = store.issue_token(store.create_license("pro"), MACHINE_A)["token"]
    body, sig = token.split(".")
    payload = lf.read_token(store.public_key, token)
    payload["max_groups"] = 9999
    forged = lf.sign_token(lf.new_private_key(), payload)
    with pytest.raises(lf.LicenseError):
        lf.read_token(store.public_key, forged)
    with pytest.raises(lf.LicenseError):
        lf.read_token(store.public_key, body + "." + sig[:-2] + "AA")
    with pytest.raises(lf.LicenseError, match="เครื่องอื่น"):
        lf.check_token(store.public_key, token, MACHINE_B)


# ---------------------------------------------------------------- activate

def test_activate_heartbeat_and_revoke(store, server, tmp_path):
    lic = store.create_license("basic", note="ลูกค้าทดสอบ")
    client = make_client(store, server, tmp_path)
    assert client.status()["active"] is False

    status = client.activate(lic["code"].lower())
    assert status["active"] and status["license"]["max_groups"] == 30

    assert client.heartbeat()["active"]
    store.set_revoked(lic["id"], True)
    status = client.heartbeat()
    assert status["active"] is False and "ระงับ" in status["message"]
    with pytest.raises(PermissionError):
        client.require()


def test_wrong_code_and_expired(store, server, tmp_path):
    client = make_client(store, server, tmp_path)
    with pytest.raises(PermissionError, match="ไม่พบ"):
        client.activate("GP-AAAA-AAAA-AAAA-AAAA")
    lic = store.create_license("trial", days=1)
    store.db.execute("UPDATE licenses SET expires = ? WHERE id = ?",
                     (lf.iso(lf.utc_now() - timedelta(minutes=1)), lic["id"]))
    store.db.commit()
    with pytest.raises(PermissionError, match="หมดอายุ"):
        client.activate(lic["code"])


def test_device_limit_and_moving(store, server, tmp_path):
    lic = store.create_license("basic")          # 1 เครื่อง
    first = make_client(store, server, tmp_path, MACHINE_A)
    second = make_client(store, server, tmp_path, MACHINE_B)
    first.activate(lic["code"])
    with pytest.raises(PermissionError, match="ครบ 1 เครื่อง"):
        second.activate(lic["code"])
    # activate ซ้ำบนเครื่องเดิมต้องผ่าน ไม่นับเป็นเครื่องที่สอง
    first.activate(lic["code"])

    first.deactivate()
    assert first.status()["active"] is False
    assert second.activate(lic["code"])["active"]
    # เครื่องที่ถูกปลดแล้ว token เก่าต้องต่ออายุไม่ได้
    assert store.devices(lic["id"], active_only=True)[0]["machine"] == MACHINE_B


def test_move_limit(store, server, tmp_path):
    lic = store.create_license("basic")
    client = make_client(store, server, tmp_path)
    for _ in range(MAX_MOVES_PER_MONTH):
        client.activate(lic["code"])
        client.deactivate()
    client.activate(lic["code"])
    with pytest.raises(PermissionError, match="ย้ายเครื่องครบ"):
        client.deactivate()
    # แอดมินปลดให้ได้เสมอ
    store.release_all(lic["id"])
    assert not store.devices(lic["id"], active_only=True)


def test_offline_grace(store, server, tmp_path):
    lic = store.create_license("pro")
    client = make_client(store, server, tmp_path)
    client.activate(lic["code"])

    def offline(*_, **__):
        raise OSError("server ดับ")

    client._http = offline
    status = client.heartbeat()
    assert status["active"] and "ติดต่อ server ไม่ได้" in status["message"]
    later = lf.utc_now() + GRACE + timedelta(minutes=1)
    assert client.status(now=later)["active"] is False


def test_rate_limit(store, server):
    for _ in range(20):
        server.post("/v1/activate", json={"code": "GP-X", "machine": MACHINE_A})
    assert server.post("/v1/activate", json={"code": "GP-X", "machine": MACHINE_A}).status_code == 429


def test_admin_cli(store, capsys, tmp_path):
    assert admin.main(["new", "--plan", "trial", "--note", "คุณเอ", "--count", "2"], store=store) == 0
    out = capsys.readouterr().out
    assert out.count("GP-") == 2 and "คุณเอ" in out
    code = out.split()[0]
    assert admin.main(["revoke", code], store=store) == 0
    assert "ระงับ" in capsys.readouterr().out
    assert admin.main(["extend", code, "--days", "30"], store=store) == 0
    cfg = tmp_path / "config.json"
    assert admin.main(["agent-config", "--server", "https://x.example/", "--out", str(cfg)], store=store) == 0
    assert '"server_url": "https://x.example"' in cfg.read_text(encoding="utf-8")


# ---------------------------------------------------------------- งานโพสต์

def test_parse_groups():
    ids, bad = jobs_mod.parse_groups(
        "123456789012345\nhttps://www.facebook.com/groups/987654321098765/?ref=x\n"
        "123456789012345, facebook.com/groups/shopname")
    assert ids == ["123456789012345", "987654321098765"]
    assert bad == ["facebook.com/groups/shopname"]


def test_vendored_poster_imports():
    poster = jobs_mod.default_poster()
    assert poster.__name__ == "post_to_groups"


class FakePoster:
    def __init__(self):
        self.calls = []

    def __call__(self, adb, serial, images, caption, group_ids, *, gap_range, dry_run,
                 log, stop, on_result, comment):
        self.calls.append(dict(serial=serial, images=images, caption=caption,
                               groups=group_ids, gap=gap_range, dry_run=dry_run, comment=comment))
        for index, gid in enumerate(group_ids, start=1):
            if stop():
                break
            log(f"กลุ่ม {gid}")
            on_result({"group_id": gid, "posted": not dry_run, "dry_run": dry_run,
                       "index": index, "total": len(group_ids)})
        return []


def agent_app(store, server, tmp_path, monkeypatch, poster):
    monkeypatch.setattr(agent_main, "DATA_DIR", tmp_path / "agent-data")
    client = make_client(store, server, tmp_path)
    runner = jobs_mod.JobRunner(tmp_path / "uploads", poster=poster)
    return TestClient(agent_main.create_app(client, runner, adb="adb", background=False)), client


def post_job(app, groups, **extra):
    data = {"serial": "PHONE1", "caption": "ขายพัดลม", "groups": groups,
            "comment": "https://s.shopee.co.th/x", "gap_min": "1", "gap_max": "2",
            "dry_run": "true", **extra}
    files = [("images", ("a.jpg", io.BytesIO(b"\xff\xd8fake"), "image/jpeg"))]
    return app.post("/api/jobs", data=data, files=files)


def wait_done(app):
    for _ in range(100):
        job = app.get("/api/jobs/current").json()["job"]
        if job["state"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError("งานไม่จบ")


def test_agent_job_flow(store, server, tmp_path, monkeypatch):
    poster = FakePoster()
    app, client = agent_app(store, server, tmp_path, monkeypatch, poster)
    assert app.get("/").status_code == 200

    # ยังไม่ activate = สั่งงานไม่ได้
    assert post_job(app, "123456789012345").status_code == 403

    lic = store.create_license("trial")          # 5 กลุ่มต่อรอบ
    assert app.post("/api/license/activate", json={"code": lic["code"]}).json()["active"]

    too_many = "\n".join(str(100000000000000 + i) for i in range(6))
    response = post_job(app, too_many)
    assert response.status_code == 403 and "ไม่เกิน 5 กลุ่ม" in response.json()["detail"]

    assert post_job(app, "facebook.com/groups/shopname").status_code == 400

    response = post_job(app, "111111111111111\n222222222222222")
    assert response.status_code == 200, response.text
    job = wait_done(app)
    assert job["state"] == "done"
    assert [r["dry_run"] for r in job["results"]] == [True, True]

    call = poster.calls[-1]
    # ระยะห่างถูกดันขึ้นเป็นขั้นต่ำ 15 วินาที แม้จะส่ง 1-2 มา
    assert call["gap"] == (agent_main.MIN_GAP, agent_main.MIN_GAP)
    assert call["comment"] == "https://s.shopee.co.th/x"
    assert call["images"][0].endswith("img1.jpg")

    # ระงับรหัสแล้ว งานใหม่ต้องถูกปฏิเสธ
    store.set_revoked(lic["id"], True)
    app.post("/api/license/refresh")
    assert post_job(app, "111111111111111").status_code == 403


def test_agent_rejects_non_images(store, server, tmp_path, monkeypatch):
    app, _ = agent_app(store, server, tmp_path, monkeypatch, FakePoster())
    app.post("/api/license/activate", json={"code": store.create_license("pro")["code"]})
    files = [("images", ("../../evil.exe", io.BytesIO(b"MZ"), "application/octet-stream"))]
    response = app.post("/api/jobs", data={"serial": "P", "caption": "x", "groups": "111111111111111"},
                        files=files)
    assert response.status_code == 400
