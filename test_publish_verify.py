"""เทสตัวตรวจของผังโพสต์ — เน้นด่าน "อยู่หน้าที่ต้องการจริงไหม"

ใช้มือถือปลอมทั้งหมด ไม่แตะเครื่องจริงและไม่ต้องมี ADB

**ที่มา** 19 ส.ค. 2026 ผังโพสต์ Shopee รายงานว่าผ่านขั้น 2-3 แต่จริงๆ หลงไปหน้า
"ยืนยันตัวตน" เพราะตัวตรวจ `screen_changed` ถามแค่ "มีอะไรเปลี่ยนไหม" ไม่ได้ถามว่า
"เปลี่ยนไปถูกที่ไหม" เทสชุดนี้ล็อกพฤติกรรมใหม่ไว้ไม่ให้ถอยกลับไปเป็นแบบเดิม
"""

from __future__ import annotations

import sys
import time
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


# ============================================================================
#  ตัวอ่านจอ "ตาบอดค้าง" — เคสจริง 30 ส.ค. 2569 (เข้าโหมดนี้ไป 19 ครั้งในวันเดียว)
#
#  Facebook Reels ล้มที่ขั้น 12 ทั้งที่ภาพหลักฐานยืนยันว่าวางแฮชแท็กครบ 5 ตัวแล้ว
#  เพราะความจำ "จอนี้อ่านไม่ได้" ติดตั้งแต่หน้าเลือกหน้าปก (วิดีโอเล่นตลอด)
#  แล้วค้างข้ามมา 4 ขั้น เนื่องจากเงื่อนไขล้างความจำคือ "ชื่อหน้าจอเปลี่ยน"
#  แต่ Facebook ใช้ชื่อเดียวกัน (ImmersiveActivity) ทั้งสองหน้า
# ============================================================================

FB_FRONT = "com.facebook.katana/com.facebook.video.creativeediting.ImmersiveActivity"


class BlindPhone:
    """มือถือปลอมที่ "อ่านผังจอไม่ได้" ได้ตามสั่ง — จำลองหน้าที่มีวิดีโอเล่นอยู่

    ชื่อหน้าจอ **ไม่เปลี่ยนเลย** ตลอดการทดสอบ เพราะนั่นคือเงื่อนไขที่ทำให้
    ของเดิมพัง — ถ้าใช้ชื่อหน้าจอที่เปลี่ยนได้ เทสจะผ่านทั้งที่บั๊กยังอยู่
    """

    def __init__(self, xml: str):
        self.readable = False
        self.xml = xml
        self.dumps = 0

    def run_adb(self, *args) -> bytes:
        joined = " ".join(str(a) for a in args)
        if "dumpsys" in joined:
            return f"mCurrentFocus=Window{{abc u0 {FB_FRONT}}}".encode("utf-8")
        if "uiautomator" in joined:
            self.dumps += 1
            return b""
        if joined.startswith("shell cat"):
            return self.xml.encode("utf-8") if self.readable else b""
        return b""


def blind_context(phone: BlindPhone) -> publish_flow.RunContext:
    """บริบทจริง — **ไม่ตัด `dump()` ออก** เพราะเรากำลังเทสตัวอ่านจอเอง"""
    return publish_flow.RunContext(
        serial="test", store=None, target="facebook_reels", screen=(1080, 2400),
        tap=lambda x, y: phone.taps.append((x, y)) if hasattr(phone, "taps") else None,
        type_text=lambda text: None,
        set_clipboard=lambda text, paste=True: None,
        run_adb=phone.run_adb,
        log=lambda message: None,
        app_package="com.facebook.katana",
    )


print("")
print("[12] เพดานความจำ 'จอนี้อ่านไม่ได้' ต้องสั้นกว่าระยะห่างระหว่างขั้น")
print("      (แต่ละขั้นห่างกัน 13-20 วินาที · ของเดิม 90 วินาทีครอบข้ามไป 4 ขั้น)")
check("UI_DUMP_BLIND_MEMO", publish_flow.UI_DUMP_BLIND_MEMO, 15.0)
truthy("ต้องไม่เกินระยะห่างระหว่างขั้นที่แคบที่สุด (13 วินาที) มากนัก",
       publish_flow.UI_DUMP_BLIND_MEMO <= 15.0)

print("")
print("[13] กดแล้วต้องลืมความจำทันที ถึงชื่อหน้าจอจะไม่เปลี่ยน ← บั๊กตัวจริง")
publish_flow.forget_blind_screen()
phone = BlindPhone(screen("#tcl #tclthailand #ทีวี"))
ctx = blind_context(phone)
check("รอบแรกอ่านไม่ได้ → คืนค่าว่าง", ctx.dump(), "")
truthy("และจดไว้ว่าจอนี้อ่านไม่ได้", publish_flow.dump_ui_blind_for() > 0)
before_dumps = phone.dumps

# จอกลับมาอ่านได้แล้ว แต่ยังไม่มีใครกดอะไร → ยังใช้ความจำได้ (ไม่เสียเวลาซ้ำ)
phone.readable = True
check("ยังไม่ได้กดอะไร = ยังใช้ความจำเดิม", ctx.dump(), "")
check("และไม่ไปเสียเวลาอ่านจอซ้ำเลย", phone.dumps, before_dumps)

# **จุดที่ของเดิมพัง** — กดแล้วชื่อหน้าจอเหมือนเดิมเป๊ะ ความจำจึงค้างต่อ
ctx.tap_at(500, 500)
truthy("กดแล้วต้องลืมความจำทันที", publish_flow.dump_ui_blind_for() == 0)
truthy("แล้วกลับมาอ่านผังจอได้จริง", "#tcl" in ctx.dump())

print("")
print("[14] ทุกช่องทางที่แตะจอต้องล้างความจำ · คำสั่งที่แค่ 'อ่าน' ต้องไม่ล้าง")


def make_blind() -> None:
    """แกล้งให้ระบบคิดว่าจอนี้อ่านไม่ได้ เพื่อดูว่าใครล้างความจำบ้าง"""
    publish_flow._ui_dump_blind_until = time.time() + 99
    publish_flow._ui_dump_blind_where = FB_FRONT


def forgot_after(name: str, action, want: bool) -> None:
    make_blind()
    action()
    got = publish_flow.dump_ui_blind_for() == 0
    check(name, got, want)


phone = BlindPhone(screen("อะไรก็ได้"))
ctx = blind_context(phone)
for label, act in (
    ("แตะจอ (tap_at)", lambda: ctx.tap_at(100, 200)),
    ("พิมพ์ข้อความ (type_text)", lambda: ctx.type_text("สวัสดี")),
    ("วางผ่านคลิปบอร์ด (set_clipboard)", lambda: ctx.set_clipboard("#tcl", True)),
    ("ปุ่มระบบ (input keyevent)",
     lambda: ctx.run_adb("shell", "input", "keyevent", "BACK")),
    ("ปัดจอ (input swipe)",
     lambda: ctx.run_adb("shell", "input", "swipe", "1", "2", "3", "4", "400")),
    ("เปิดแอป (monkey)",
     lambda: ctx.run_adb("shell", "monkey", "-p", "com.facebook.katana", "1")),
    ("ปิดแอป (am force-stop)",
     lambda: ctx.run_adb("shell", "am", "force-stop", "com.facebook.katana")),
):
    forgot_after(f"{label} → ต้องลืม", act, True)

for label, act in (
    ("สั่งดูดผังจอ (uiautomator dump)",
     lambda: ctx.run_adb("shell", "uiautomator", "dump", "/sdcard/x.xml")),
    ("อ่านไฟล์ผัง (cat)", lambda: ctx.run_adb("shell", "cat", "/sdcard/x.xml")),
    ("ถามชื่อหน้าจอ (dumpsys)",
     lambda: ctx.run_adb("shell", "dumpsys", "window", "displays")),
    ("แคปหน้าจอ (screencap)",
     lambda: ctx.run_adb("exec-out", "screencap", "-p")),
):
    forgot_after(f"{label} → ต้อง**ไม่**ลืม", act, False)

publish_flow.forget_blind_screen()

print("")
print("[15] ตรวจแท็ก: อ่านจอไม่ได้ ต้องบอก 'ยังไม่ได้ตรวจ' ไม่ใช่ 'ไม่เห็นแท็ก'")
print("      (เคสจริง 30 ส.ค. 13:40:29 — แท็กครบ 5 ตัวอยู่ในช่อง แต่รายงานว่าไม่เห็น)")
TAGS = ["#tcl", "#tclthailand", "#ทีวี", "#รีวิว", "#ลดราคา"]


def tag_context(xml: str):
    ctx = context_for(Phone(xml, FB_FRONT), app_package="com.facebook.katana")
    ctx.tag_results = [{"tag": t, "count": None, "raw": "", "used": True} for t in TAGS]
    return ctx


try:
    publish_flow.verify_step(tag_context(""), step_of(verify="tags_present"), BEFORE)
    check("อ่านจอไม่ได้ต้องไม่ผ่าน", "ผ่าน", "โยน StepError")
except publish_flow.StepError as error:
    truthy("บอกว่าอ่านผังจอไม่ได้", "อ่านผังจอไม่ได้" in str(error))
    truthy("บอกชัดว่ายังไม่ได้ตรวจ", "ยังไม่ได้ตรวจ" in str(error))
    truthy("ห้ามพูดว่า 'ยังไม่เห็นแท็ก'", "ยังไม่เห็นแท็ก" not in str(error))
    print(f"       ข้อความที่ได้: {error}")

message = publish_flow.verify_step(
    tag_context(screen(" ".join(TAGS))), step_of(verify="tags_present"), BEFORE)
truthy("อ่านจอได้ + เจอครบ = ผ่านเหมือนเดิม", "เห็นแท็กครบ 5 ตัว" in message)

try:
    publish_flow.verify_step(tag_context(screen("ช่องคำอธิบายว่างอยู่")),
                             step_of(verify="tags_present"), BEFORE)
    check("อ่านจอได้แต่ไม่มีแท็กต้องไม่ผ่าน", "ผ่าน", "โยน StepError")
except publish_flow.StepError as error:
    truthy("อ่านจอได้แต่ไม่มีแท็ก = 'ยังไม่เห็นแท็ก' เหมือนเดิม",
           "ยังไม่เห็นแท็ก" in str(error))

print("")
print("[16] 'ข้อความหายไปแล้ว': ตาบอดแล้วต้อง**ไม่ผ่าน** — ของเดิมผ่าน = อันตรายสุด")
gone = step_of(verify="text_gone", verify_text="กำลังอัปโหลด")
try:
    publish_flow.verify_step(
        context_for(Phone("", FB_FRONT), app_package="com.facebook.katana"),
        gone, BEFORE)
    check("ตาบอดต้องไม่ผ่าน", "ผ่าน", "โยน StepError")
except publish_flow.StepError as error:
    truthy("ตาบอดต้องไม่ผ่าน", "ยืนยันไม่ได้" in str(error))
    print(f"       ข้อความที่ได้: {error}")

message = publish_flow.verify_step(
    context_for(Phone(screen("โพสต์เสร็จแล้ว"), FB_FRONT),
                app_package="com.facebook.katana"), gone, BEFORE)
truthy("อ่านจอได้ + ไม่มีข้อความนั้นแล้ว = ผ่านเหมือนเดิม", "หายไปแล้ว" in message)

try:
    publish_flow.verify_step(
        context_for(Phone(screen("กำลังอัปโหลด 40%"), FB_FRONT),
                    app_package="com.facebook.katana"), gone, BEFORE)
    check("ข้อความยังอยู่ต้องไม่ผ่าน", "ผ่าน", "โยน StepError")
except publish_flow.StepError as error:
    truthy("ข้อความยังอยู่ = 'ยังอยู่' เหมือนเดิม", "ยังอยู่" in str(error))

print("")
print("[17] กล่อง Shopee จำกัดโพสต์ต้องเป็น hard stop ไม่ใช่โฆษณา")
for limit_message in (
    "Post too many video, please have a rest",
    "You have posted too many videos. Please take a rest.",
    "โพสต์วิดีโอมากเกินไป กรุณาพักสักครู่",
):
    truthy("จำข้อความ limit: " + limit_message,
           publish_flow.is_shopee_post_limit(screen(limit_message)))
truthy("ข้อความทั่วไปไม่ใช่ limit",
       publish_flow.is_shopee_post_limit(screen("Post your next video")), False)

phone = Phone(screen("Post too many video, please have a rest"),
              "com.shopee.th/com.shopee.sz.luckyvideo.publishvideo.PublishVideoActivity")
try:
    publish_flow.verify_step(
        context_for(phone),
        step_of(id="post", verify="left_screen", verify_text="PublishVideoActivity"),
        BEFORE,
    )
    check("เจอ limit ต้องหยุดทันที", "ผ่าน", "โยน StopAutomationError")
except publish_flow.StopAutomationError as error:
    check("รหัสเหตุ", error.code, "shopee_post_limit")
    check("ปิดเฉพาะสวิตช์", error.auto_key, "shopee_post")
    truthy("บอกว่าห้าม retry", error.payload().get("retry"), False)

print("")
print("[18] run_flow ต้องส่งสัญญาณให้ caller และห้ามเข้า dismiss/retry")


class OneStepStore:
    def sequence(self, target: str) -> list[publish_flow.Step]:
        return [publish_flow.Step(id="post", name="กดโพสต์")]


calls = {"run": 0, "dismiss": 0, "report": 0}
old_run_step = publish_flow.run_step
old_dismiss_ads = publish_flow.dismiss_ads


def raise_post_limit(context, step):
    calls["run"] += 1
    raise publish_flow.StopAutomationError(
        publish_flow.SHOPEE_POST_LIMIT_REASON,
        code=publish_flow.SHOPEE_POST_LIMIT_CODE,
        auto_key=publish_flow.SHOPEE_POST_LIMIT_AUTO_KEY,
    )


def count_dismiss(*args, **kwargs):
    calls["dismiss"] += 1
    return ["ไม่ควรถูกเรียก"]


try:
    publish_flow.run_step = raise_post_limit
    publish_flow.dismiss_ads = count_dismiss
    ctx = publish_flow.RunContext(
        serial="test", store=OneStepStore(), target="shopee_video",
        screen=(1080, 2400), tap=lambda x, y: None,
        type_text=lambda value: None, run_adb=lambda *args: b"",
        log=lambda message: None,
        report=lambda step, ok, message: calls.__setitem__(
            "report", calls["report"] + 1),
    )
    result = publish_flow.run_flow(ctx)
finally:
    publish_flow.run_step = old_run_step
    publish_flow.dismiss_ads = old_dismiss_ads

check("ไม่ retry ขั้น Post", calls["run"], 1)
check("ไม่เรียกตัวปิดโฆษณา", calls["dismiss"], 0)
check("ยัง report หนึ่งครั้งเพื่อเก็บ screenshot/XML", calls["report"], 1)
check("caller ได้ auto_key", result["automation_stop"]["auto_key"], "shopee_post")
check("caller ได้ code", result["automation_stop"]["code"], "shopee_post_limit")
truthy("error หลักมีเหตุผลพร้อมแจ้งผู้ใช้", "Post too many" in result["error"])
truthy("ผลรวมต้องไม่สำเร็จ", result["ok"], False)
truthy("ขั้นนี้ห้ามถูกนับว่าเสร็จ", result["results"][-1]["ok"], False)

print("")
print("[19] ก่อนกด Live & Video ต้องจับโฆษณาที่โผล่ช้าและห้ามกดผ่านโฆษณาที่ปิดไม่ได้")
clean_xml = screen("หน้าแรก Shopee", "Live & Video")
late_ad_xml = screen("โฆษณา", "ปิดโฆษณา")
phone = Phone(clean_xml, "com.shopee.th/HomeActivity")
ctx = context_for(phone)
reads = iter([late_ad_xml, clean_xml, clean_xml, clean_xml])
ctx.dump = lambda: next(reads, clean_xml)                  # type: ignore[method-assign]
old_sleep = publish_flow.time.sleep
old_gap = publish_flow.SHOPEE_LAUNCH_GUARD_GAP
try:
    publish_flow.time.sleep = lambda _seconds: None
    publish_flow.SHOPEE_LAUNCH_GUARD_GAP = 0
    notes = publish_flow.guard_shopee_before_live(ctx, clean_xml)
finally:
    publish_flow.time.sleep = old_sleep
    publish_flow.SHOPEE_LAUNCH_GUARD_GAP = old_gap
check("ปิดโฆษณาที่โผล่หลังอ่านครั้งแรก", len(notes), 1)
check("แตะเฉพาะปุ่มปิดหนึ่งครั้ง", len(phone.taps), 1)

phone = Phone(screen("โฆษณา", "ดูรายละเอียด"), "com.shopee.th/HomeActivity")
ctx = context_for(phone)
try:
    publish_flow.guard_shopee_before_live(ctx, phone.xml)
    check("เห็นโฆษณาแต่ไม่มีปุ่มปิดต้องไม่เดินต่อ", "ผ่าน", "โยน StepError")
except publish_flow.StepError as error:
    truthy("เห็นโฆษณาแต่ไม่มีปุ่มปิดต้องไม่เดินต่อ", "หาปุ่มปิด" in str(error))

print("")
print("[20] ด่าน Shopee ต้องทำงานก่อนนิ้วแตะ Live & Video")


class LiveStore:
    def point_for(self, target: str, step_id: str, width: int, height: int):
        return (540, 2200)


events: list[str] = []
phone = Phone(clean_xml, "com.shopee.th/HomeActivity")
ctx = publish_flow.RunContext(
    serial="test", store=LiveStore(), target="shopee_video", screen=(1080, 2400),
    tap=lambda x, y: events.append("tap"), type_text=lambda text: None,
    run_adb=phone.run_adb, log=lambda message: None, tap_jitter=0, settle_jitter=0,
)
ctx.dump = lambda: clean_xml                               # type: ignore[method-assign]
old_guard = publish_flow.guard_shopee_before_live
try:
    publish_flow.guard_shopee_before_live = (
        lambda context, initial_xml="": events.append("guard") or []
    )
    publish_flow.run_step(
        ctx,
        publish_flow.Step(
            id="live_and_video", name="กด Live & Video", kind="tap",
            settle=0, verify="none",
        ),
    )
finally:
    publish_flow.guard_shopee_before_live = old_guard
check("ตรวจโฆษณาก่อนแตะ", events, ["guard", "tap"])

print("")
print("[21] เลือกสินค้า Shopee ต้องเกาะ checkbox ในรายการ ไม่ใช้พิกัดเก่า")
product_xml = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy rotation="0"><node text="" bounds="[0,0][720,1600]">
  <node text="รายการสินค้า" clickable="false" bounds="[24,824][712,862]" />
  <node text="" clickable="true" bounds="[24,976][60,1012]" />
  <node text="PATARA รุ่น UNIVERSE" clickable="false" bounds="[272,894][657,958]" />
  <node text="เลือกทั้งหมด" clickable="false" bounds="[80,1428][226,1464]" />
  <node text="เพิ่ม" clickable="false" bounds="[446,1425][497,1465]" />
</node></hierarchy>"""
check("ได้กึ่งกลาง checkbox รายการแรก",
      publish_flow.find_shopee_product_checkbox(product_xml, 720, 1600),
      (42, 994))

moved_xml = product_xml.replace("[24,976][60,1012]", "[24,1100][60,1136]")
check("รายการเลื่อนแล้วต้องตามตำแหน่งใหม่",
      publish_flow.find_shopee_product_checkbox(moved_xml, 720, 1600),
      (42, 1118))

check("ไม่มีหัวรายการต้องไม่เดาพิกัด",
      publish_flow.find_shopee_product_checkbox(
          product_xml.replace("รายการสินค้า", "สินค้า"), 720, 1600),
      None)

print("")
print("=" * 56)
print("ผ่าน {} · ไม่ผ่าน {}".format(PASS, FAIL))
print("=" * 56)
sys.exit(1 if FAIL else 0)
