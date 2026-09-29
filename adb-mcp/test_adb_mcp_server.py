"""เทส ADB MCP server — ไม่ต้องมีมือถือ ใช้ adb จำลองที่จำคำสั่งไว้ตรวจ

    python -m pytest adb-mcp -q
"""

from __future__ import annotations

import base64
import struct
import subprocess
import zlib

import pytest

import adb_mcp_server as srv

UI_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.example.app" bounds="[0,0][1080,2400]" text="">
    <node class="android.widget.Button" package="com.example.app" text="เข้าสู่ระบบ" resource-id="com.example.app:id/login" clickable="true" enabled="true" bounds="[100,1800][980,1950]" />
    <node class="android.widget.EditText" package="com.example.app" content-desc="อีเมล" resource-id="com.example.app:id/email" clickable="true" bounds="[100,1000][980,1120]" />
    <node class="android.view.View" package="com.example.app" bounds="[0,0][10,10]" />
  </node>
</hierarchy>"""


def make_png(width=1080, height=2400) -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    body = zlib.compress(b"\x00" + b"\xff\xff\xff" * width)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", body) + chunk(b"IEND", b"")


class FakeAdb:
    """ยืน subprocess.run — จำคำสั่งไว้ให้เทสตรวจ และตอบผลตามคำสั่ง"""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.ime = "com.google.android.inputmethod.latin/.LatinIME"

    def __call__(self, cmd, capture_output, timeout, text, creationflags=0):
        args = cmd[1:]
        self.calls.append(args)
        out: object = "" if text else b""
        if args[:2] == ["devices", "-l"]:
            out = ("List of devices attached\n"
                   "TEST01 device product:a14 model:Galaxy_A14 device:a14\n"
                   "PROD99 device model:Redmi\n")
        elif "screencap" in args:
            out = make_png()
        elif args[-1:] == ["/sdcard/adb_mcp_ui.xml"] and "cat" in args:
            out = UI_XML
        elif "default_input_method" in args:
            out = self.ime + "\n"
        elif args[:3] == ["-s", "TEST01", "install"]:
            out = "Success\n"
        return subprocess.CompletedProcess(cmd, 0, out, "" if text else b"")


@pytest.fixture()
def adb(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "DATA_DIR", tmp_path)
    monkeypatch.setattr(srv, "UPLOAD_DIR", tmp_path / "uploads")
    fake = FakeAdb()
    return srv.Adb(adb="adb", allowed={"TEST01"}, runner=fake), fake


def tools(adb_obj):
    """คืน map ชื่อเครื่องมือ -> ฟังก์ชันจริง (เรียกตรงเพื่อให้ AdbError เด้งออกมาไม่ถูกห่อ)"""
    server = srv.build_server(adb_obj)
    return {tool.name: tool.fn for tool in server._tool_manager.list_tools()}


def call(_tools, _name, **kwargs):
    return _tools[_name](**kwargs)


# ---------------------------------------------------------------- ผังจอ

def test_summarize_ui_keeps_useful_nodes():
    text = srv.summarize_ui(UI_XML)
    assert "com.example.app" in text
    assert "เข้าสู่ระบบ" in text
    assert "(540,1875)" in text          # กึ่งกลางปุ่ม login
    assert "(540,1060)" in text          # กึ่งกลางช่องอีเมล
    assert "id=login" in text
    # node ขนาด 10x10 ที่ไม่มีข้อความและกดไม่ได้ ต้องถูกตัดออก
    assert text.count("\n") <= 5


def test_summarize_ui_bad_xml():
    with pytest.raises(srv.AdbError):
        srv.summarize_ui("<hierarchy><node bounds=")


# ---------------------------------------------------------------- ความปลอดภัย serial

def test_serial_allowlist(adb):
    obj, _ = adb
    assert obj.check_serial("TEST01") == "TEST01"
    with pytest.raises(srv.AdbError, match="ไม่อยู่ในรายการ"):
        obj.check_serial("PROD99")
    with pytest.raises(srv.AdbError, match="ไม่ถูกต้อง"):
        obj.check_serial("bad serial!")


def test_devices_marks_allowed(adb):
    obj, _ = adb
    rows = {d["serial"]: d for d in obj.devices()}
    assert rows["TEST01"]["allowed"] is True
    assert rows["PROD99"]["allowed"] is False
    assert rows["TEST01"]["model"] == "Galaxy_A14"


# ---------------------------------------------------------------- เครื่องมือ

def test_screenshot_reports_real_size(adb):
    obj, _ = adb
    result = call(tools(obj), "screenshot", serial="TEST01", max_side=0)
    assert any("1080x2400" in str(part) for part in result)


def test_tap_uses_input(adb):
    obj, fake = adb
    call(tools(obj), "tap", serial="TEST01", x=540, y=1875)
    assert ["-s", "TEST01", "shell", "input", "tap", "540", "1875"] in fake.calls


def test_tap_blocks_unlisted_device(adb):
    obj, _ = adb
    with pytest.raises(srv.AdbError, match="ไม่อยู่ในรายการ"):
        call(tools(obj), "tap", serial="PROD99", x=1, y=1)


def test_type_ascii(adb):
    obj, fake = adb
    call(tools(obj), "type_text", serial="TEST01", text="hello world")
    text_calls = [c for c in fake.calls if "text" in c and "input" in c]
    assert text_calls and "hello%sworld" in text_calls[-1][-1]


def test_type_thai_requires_adb_keyboard(adb):
    obj, fake = adb
    with pytest.raises(srv.AdbError, match="ADBKeyboard"):
        call(tools(obj), "type_text", serial="TEST01", text="สวัสดี")
    fake.ime = srv.ADB_KEYBOARD_IME
    call(tools(obj), "type_text", serial="TEST01", text="สวัสดี")
    broadcasts = [c for c in fake.calls if "ADB_INPUT_B64" in c]
    assert broadcasts
    payload = broadcasts[-1][broadcasts[-1].index("msg") + 1]
    assert base64.b64decode(payload).decode("utf-8") == "สวัสดี"


def test_key_unknown(adb):
    obj, _ = adb
    with pytest.raises(srv.AdbError, match="ไม่รู้จักปุ่ม"):
        call(tools(obj), "key", serial="TEST01", name="FLY")


def test_launch_app_validates_package(adb):
    obj, _ = adb
    with pytest.raises(srv.AdbError, match="แพ็กเกจ"):
        call(tools(obj), "launch_app", serial="TEST01", package="not a package")


def test_install_from_upload(adb):
    obj, _ = adb
    apk = b"PK\x03\x04" + b"0" * 40
    half = len(apk) // 2
    call(tools(obj), "upload_chunk", name="app.apk",
         data_b64=base64.b64encode(apk[:half]).decode(), append=False)
    call(tools(obj), "upload_chunk", name="app.apk",
         data_b64=base64.b64encode(apk[half:]).decode(), append=True)
    assert (srv.UPLOAD_DIR / "app.apk").read_bytes() == apk
    result = call(tools(obj), "install_apk", serial="TEST01", uploaded_name="app.apk")
    assert "Success" in result


def test_install_rejects_non_apk(adb):
    obj, _ = adb
    call(tools(obj), "upload_chunk", name="bad.apk",
         data_b64=base64.b64encode(b"<html>").decode(), append=False)
    with pytest.raises(srv.AdbError, match="ไม่ใช่ .apk"):
        call(tools(obj), "install_apk", serial="TEST01", uploaded_name="bad.apk")


def test_upload_name_guard(adb):
    obj, _ = adb
    with pytest.raises(srv.AdbError, match="ชื่อไฟล์"):
        call(tools(obj), "upload_chunk", name="../evil", data_b64="AA==", append=False)


def test_shell_disabled_by_default(adb):
    obj, _ = adb
    with pytest.raises(srv.AdbError, match="ปิดอยู่"):
        call(tools(obj), "shell", serial="TEST01", command="rm -rf /")


def test_set_adb_keyboard_roundtrip(adb):
    obj, fake = adb
    call(tools(obj), "set_adb_keyboard", serial="TEST01", enable=True)
    assert any("set" in c and srv.ADB_KEYBOARD_IME in c for c in fake.calls)
    message = call(tools(obj), "set_adb_keyboard", serial="TEST01", enable=False)
    assert "LatinIME" in message


# ---------------------------------------------------------------- ชั้นรหัสลับ

def test_secret_path_guard():
    import anyio

    seen = {}

    async def app(scope, receive, send):
        seen["path"] = scope["path"]
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    guard = srv.SecretPathGuard(app, "s3cr3t")

    async def hit(path):
        status = {}
        sent = []

        async def send(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
            else:
                sent.append(msg.get("body", b""))

        await guard({"type": "http", "path": path}, None, send)
        return status["code"], b"".join(sent)

    code, _ = anyio.run(hit, "/wrong/mcp")
    assert code == 404 and "path" not in seen
    code, body = anyio.run(hit, "/s3cr3t/mcp")
    assert code == 200 and seen["path"] == "/mcp" and body == b"ok"
