"""เทสตัวตรวจของผังโพสต์ — เน้นด่าน "อยู่หน้าที่ต้องการจริงไหม"

ใช้มือถือปลอมทั้งหมด ไม่แตะเครื่องจริงและไม่ต้องมี ADB

**ที่มา** 19 ส.ค. 2026 ผังโพสต์ Shopee รายงานว่าผ่านขั้น 2-3 แต่จริงๆ หลงไปหน้า
"ยืนยันตัวตน" เพราะตัวตรวจ `screen_changed` ถามแค่ "มีอะไรเปลี่ยนไหม" ไม่ได้ถามว่า
"เปลี่ยนไปถูกที่ไหม" เทสชุดนี้ล็อกพฤติกรรมใหม่ไว้ไม่ให้ถอยกลับไปเป็นแบบเดิม
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publish_flow                                          # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, got, want) -> None:
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}\n       ได้: {got!r}\n       ควรได้: {want!r}")


def truthy(name: str, got, want: bool = True) -> None:
    check(name, bool(got), want)


def screen(*labels: str) -> str:
    """ผังจอปลอมแบบง่าย — มีแค่ข้อความที่เราสนใจ"""
    nodes = "".join(
        f'<node index="0" text="{text}" resource-id="" class="android.widget.TextView" '
        f'package="com.example" content-desc="" checkable="false" checked="false" '
        f'clickable="true" bounds="[0,{i * 100}][1080,{i * 100 + 90}]" />'
        for i, text in enumerate(labels)
    )
    return f"<?xml version='1.0'?><hierarchy rotation=\"0\">{nodes}</hierarchy>"


class Phone:
    """มือถือปลอม — จอเปลี่ยนได้ และบอกได้ว่าแอปไหนอยู่หน้าสุด"""

    def __init__(self, xml: str, front: str):
        self.xml = xml
        self.front = front
        self.taps: list[tuple[int, int]] = []

    def run_adb(self, *args) -> bytes:
        joined = " ".join(str(a) for a in args)
        if "dumpsys window" in joined or "displays" in joined:
            return f"mCurrentFocus=Window{{abc u0 {self.front}}}".encode("utf-8")
        if "uiautomator" in joined or "cat" in joined:
            return self.xml.encode("utf-8")
        return b""


def context_for(phone: Phone, app_package: str = "com.shopee.th"):
    ctx = publish_flow.RunContext(
        serial="test", store=None, target="shopee_video", screen=(1080, 2400),
        tap=lambda x, y: phone.taps.append((x, y)),
        type_text=lambda text: None,
        run_adb=phone.run_adb,
        log=lambda message: None,
        app_package=app_package,
    )
    # ตัดการอ่านผังจริงออก ให้ดึงจากมือถือปลอมแทน
    ctx.dump = lambda: phone.xml                              # type: ignore[method-assign]
    ctx.signature = lambda: publish_flow.screen_signature(phone.xml)  # type: ignore
    return ctx


def step_of(**kwargs) -> publish_flow.Step:
    base = {"id": "t", "name": "ขั้นทดสอบ", "kind": "tap",
            "verify": "screen_changed", "verify_timeout": 1.0}
    base.update(kwargs)
    return publish_flow.Step(**base)


BEFORE = publish_flow.screen_signature(screen("หน้าเดิม"))

print("\n[1] จอไม่เปลี่ยน = ไม่ผ่านเหมือนเดิม")
phone = Phone(screen("หน้าเดิม"), "com.shopee.th/HomeActivity")
try:
    publish_flow.verify_step(context_for(phone), step_of(), BEFORE)
    check("จอเหมือนเดิมต้องไม่ผ่าน", "ผ่าน", "โยน StepError")
except publish_flow.StepError as error:
    truthy("จอเหมือนเดิมต้องไม่ผ่าน", "หน้าจอยังเหมือนเดิม" in str(error))

print("\n[2] จอเปลี่ยน + อยู่แอปเดิม = ผ่าน และต้องบอกว่าไปโผล่หน้าไหน")
phone = Phone(screen("หน้าใหม่"), "com.shopee.th/VideoFeedActivity")
message = publish_flow.verify_step(context_for(phone), step_of(), BEFORE)
truthy("ผ่าน", "หน้าจอเปลี่ยนแล้ว" in message)
truthy("บอกชื่อหน้าจอปลายทางด้วย", "VideoFeedActivity" in message)
print(f"       ข้อความที่ได้: {message}")

print("\n[3] จอเปลี่ยนแต่หลุดออกจากแอป = ต้องไม่ผ่าน (ของเดิมนับว่าผ่าน)")
phone = Phone(screen("หน้าใหม่"), "com.android.chrome/Main")
try:
    publish_flow.verify_step(context_for(phone), step_of(), BEFORE)
    check("หลุดออกจากแอปต้องไม่ผ่าน", "ผ่าน", "โยน StepError")
except publish_flow.StepError as error:
    truthy("หลุดออกจากแอปต้องไม่ผ่าน", "หลุดออกจากแอป" in str(error))
    truthy("บอกว่าหลุดไปแอปไหน", "com.android.chrome" in str(error))
    print(f"       ข้อความที่ได้: {error}")

print("\n[4] ไม่ได้ตั้ง app_package = ไม่ตรวจเรื่องแอป (ผังเก่ายังทำงานเหมือนเดิม)")
phone = Phone(screen("หน้าใหม่"), "com.android.chrome/Main")
message = publish_flow.verify_step(context_for(phone, app_package=""), step_of(), BEFORE)
truthy("ยังผ่านตามเดิม", "หน้าจอเปลี่ยนแล้ว" in message)

print("\n[5] ตั้งข้อความที่ต้องเห็นไว้ด้วย — เจอ = ผ่าน")
phone = Phone(screen("หน้าใหม่", "ไลฟ์ & วิดีโอ"), "com.shopee.th/VideoFeedActivity")
message = publish_flow.verify_step(
    context_for(phone), step_of(verify_text="ไลฟ์"), BEFORE)
truthy("เจอข้อความที่รอ = ผ่าน", "หน้าจอเปลี่ยนแล้ว" in message)

print("\n[6] ตั้งข้อความที่ต้องเห็น — จอเปลี่ยนแต่ไม่เจอ = ไม่ผ่าน")
print("      (นี่คือเคสจริงที่หลุดไปหน้า 'ยืนยันตัวตน' แล้วระบบบอกว่าผ่าน)")
phone = Phone(screen("ยืนยันตัวตน", "Refresh"), "com.shopee.th/WebPageActivity")
try:
    publish_flow.verify_step(context_for(phone), step_of(verify_text="ไลฟ์"), BEFORE)
    check("ไม่เจอข้อความต้องไม่ผ่าน", "ผ่าน", "โยน StepError")
except publish_flow.StepError as error:
    truthy("ไม่เจอข้อความต้องไม่ผ่าน", "ยังไม่เจอ" in str(error))
    truthy("บอกด้วยว่าตอนนี้อยู่หน้าไหน", "WebPageActivity" in str(error))
    print(f"       ข้อความที่ได้: {error}")

print("\n[7] ค่าปริยายของแต่ละชนิดขั้น")
check("วางลิงก์สินค้า → text_appears",
      publish_flow.DEFAULT_VERIFY["paste_link"], "text_appears")
check("ใส่แฮชแท็ก → tags_present",
      publish_flow.DEFAULT_VERIFY["type_hashtag"], "tags_present")
check("แตะ → screen_changed (เหมือนเดิม)",
      publish_flow.DEFAULT_VERIFY["tap"], "screen_changed")

print("\n[8] ขั้นในผังตั้งต้นของ Shopee Video")
shopee = {s["id"]: s for s in publish_flow.DEFAULT_SEQUENCES["shopee_video"]}
check("วางลิงก์ Shopee ใช้ text_appears",
      shopee["link_paste"].get("verify"), "text_appears")
truthy("และระบุข้อความที่ต้องเห็นไว้ด้วย",
       bool(shopee["link_paste"].get("verify_text")))
print(f"       verify_text = {shopee['link_paste'].get('verify_text')!r}")
check("พิมพ์ # ตามลิสต์ ใช้ tags_present",
      shopee["hashtag_type"].get("verify"), "tags_present")


print("")
print("[9] text_appears ที่ไม่ได้บอกว่าข้อความอะไร ต้องไม่แอบผ่าน")
phone = Phone(screen("อะไรก็ได้"), "com.shopee.th/Any")
try:
    publish_flow.verify_step(context_for(phone),
                             step_of(verify="text_appears", verify_text=""), BEFORE)
    check("ไม่ระบุข้อความต้องไม่ผ่าน", "ผ่าน", "โยน StepError")
except publish_flow.StepError as error:
    truthy("ไม่ระบุข้อความต้องไม่ผ่าน", "ไม่ได้บอกว่าข้อความอะไร" in str(error))

print("")
print("[10] ไม่ระบุข้อความ แต่ขั้นนี้วางลิงก์ไป ใช้ลิงก์นั้นตรวจแทน")
link = "https://s.shopee.co.th/7Act1c1o5F"
phone = Phone(screen("ช่องลิงก์", link), "com.shopee.th/Any")
message = publish_flow.verify_step(
    context_for(phone), step_of(verify="text_appears", verify_text=""), BEFORE, typed=link)
truthy("เจอลิงก์ที่วาง = ผ่าน", "เจอข้อความที่รอ" in message)
phone = Phone(screen("ช่องลิงก์ว่าง"), "com.shopee.th/Any")
try:
    publish_flow.verify_step(context_for(phone),
                             step_of(verify="text_appears", verify_text=""), BEFORE, typed=link)
    check("ลิงก์ไม่อยู่บนจอต้องไม่ผ่าน", "ผ่าน", "โยน StepError")
except publish_flow.StepError as error:
    truthy("ลิงก์ไม่อยู่บนจอต้องไม่ผ่าน", "ยังไม่เจอข้อความ" in str(error))

print("")
print("[11] FOCUS_RE อ่านชื่อหน้าจอจากรูปแบบจริงได้")
cases = [
    (b"mCurrentFocus=Window{e36e918 u0 com.shopee.th/com.shopee.app.ui.home.HomeActivity_}",
     "com.shopee.th/com.shopee.app.ui.home.HomeActivity_"),
    (b"mCurrentFocus=Window{5c75f91 u0 com.facebook.katana/com.facebook.Composer}",
     "com.facebook.katana/com.facebook.Composer"),
    (b"mCurrentFocus=Window{e36e918 u0 NotificationShade}", ""),
    (b"mCurrentFocus=null", ""),
]
for raw, want in cases:
    check("อ่าน " + raw.decode()[:44], publish_flow.foreground(lambda *a, r=raw: r), want)

print("")
print("=" * 56)
print("ผ่าน {} · ไม่ผ่าน {}".format(PASS, FAIL))
print("=" * 56)
sys.exit(1 if FAIL else 0)
