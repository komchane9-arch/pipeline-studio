# -*- coding: utf-8 -*-
"""ประกอบไฟล์ APK ของแอปโน้ต แล้วลงเครื่องให้เลย

เจ้าของสั่ง 21 ก.ย. 2569 — "ติดตั้งเป็น apk ในเครื่องผมเลย"

**ไม่ใช้ Gradle โดยตั้งใจ** แอปนี้มีไฟล์ Java ไฟล์เดียวและไม่พึ่งไลบรารีข้างนอก
เลย การลง Gradle เพิ่มอีก 130 MB เพื่อมาสั่งงานเครื่องมือ 4 ตัวที่เราเรียกเองได้
คือความซับซ้อนที่ไม่จำเป็น และเวลาพังจะไล่ยากกว่าเดิม

ขั้นตอน
    1. aapt2 compile   แปลง res/ เป็นรูปแบบที่ Android อ่านได้
    2. aapt2 link      ประกอบ manifest + res เป็นโครง apk และสร้าง R.java
    3. javac           แปลโค้ด Java
    4. d8              แปลงเป็น dex (รูปแบบที่เครื่อง Android รันได้)
    5. zip + zipalign  ยัด dex เข้าไปแล้วจัดแถวไฟล์
    6. apksigner       เซ็นชื่อ (ไม่เซ็น = เครื่องไม่ยอมติดตั้ง)
    7. adb install     ลงเครื่อง

**กุญแจเซ็นชื่อเก็บไว้ที่ data/android-notes/ ซึ่งไม่เข้า git**
ถ้ากุญแจหาย จะอัปเดตทับแอปเดิมไม่ได้ ต้องถอนแล้วลงใหม่ (โน้ตไม่หายเพราะอยู่บนคอม)

    python build.py                 ประกอบอย่างเดียว
    python build.py --install       ประกอบแล้วลงเครื่องที่ต่ออยู่
    python build.py --install --serial 7a95129e
"""
import argparse
import io
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
STUDIO = HERE.parent
BUILD = HERE / "build"
SDK = Path(os.environ.get("ANDROID_HOME")
           or Path.home() / "AppData/Local/Android/Sdk")
ADB = STUDIO.parent / "7.web app/tools/platform-tools/adb.exe"

KEY_DIR = STUDIO / "data" / "android-notes"
KEYSTORE = KEY_DIR / "notes.jks"
KEY_ALIAS = "notes"
KEY_PASS = "pipeline-notes"       # แอปในวงส่วนตัว ไม่ได้ปล่อยขึ้นสโตร์
MIN_SDK, TARGET_SDK = "24", "34"

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def die(why: str) -> None:
    print(f"\n❌ {why}")
    sys.exit(1)


def run(args, why: str, **kw):
    """สั่งงานหนึ่งขั้น — พังแล้วต้องดังและบอกว่าเครื่องมือตัวไหนว่าอะไร"""
    done = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          creationflags=NO_WINDOW, **kw)
    if done.returncode:
        print(f"\n❌ {why} ไม่ผ่าน (รหัส {done.returncode})")
        print("   คำสั่ง:", " ".join(str(a) for a in args)[:400])
        out = (done.stdout or "").strip()
        err = (done.stderr or "").strip()
        if out:
            print("   ออกมาว่า:", out[:1500])
        if err:
            print("   ผิดพลาด:", err[:1500])
        sys.exit(1)
    print(f"✅ {why}")
    return done


def newest(folder: Path, pattern: str = "*") -> Path | None:
    hits = sorted(folder.glob(pattern)) if folder.is_dir() else []
    return hits[-1] if hits else None


def find_tools() -> dict:
    """หาเครื่องมือจาก SDK — ขาดตัวไหนต้องบอกชื่อตัวนั้น ไม่ใช่บอกรวมๆ ว่าไม่มี SDK"""
    if not SDK.is_dir():
        die(f"ไม่มีชุดเครื่องมือ Android ที่ {SDK}\n"
            "   ต้องโหลด commandline-tools ของ Google มาก่อน")
    tools_dir = newest(SDK / "build-tools")
    if tools_dir is None:
        die(f"ไม่มีโฟลเดอร์ build-tools ใน {SDK}\n"
            '   สั่ง: sdkmanager "build-tools;34.0.0"')
    android_jar = None
    for plat in sorted((SDK / "platforms").glob("android-*"), reverse=True):
        if (plat / "android.jar").is_file():
            android_jar = plat / "android.jar"
            break
    if android_jar is None:
        die(f"ไม่มี android.jar ใน {SDK / 'platforms'}\n"
            '   สั่ง: sdkmanager "platforms;android-34"')

    exe = ".exe" if os.name == "nt" else ""
    bat = ".bat" if os.name == "nt" else ""
    tools = {
        "aapt2": tools_dir / f"aapt2{exe}",
        "d8": tools_dir / f"d8{bat}",
        "zipalign": tools_dir / f"zipalign{exe}",
        "apksigner": tools_dir / f"apksigner{bat}",
        "android_jar": android_jar,
    }
    for name, path in tools.items():
        if not Path(path).is_file():
            die(f"ไม่เจอ {name} ที่ {path}")
    print(f"ใช้ build-tools {tools_dir.name} · {android_jar.parent.name}")
    return tools


def ensure_key() -> None:
    if KEYSTORE.is_file():
        print(f"ใช้กุญแจเดิมที่ {KEYSTORE}")
        return
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    keytool = Path(os.environ.get("JAVA_HOME", "")) / "bin" / "keytool"
    keytool = keytool if keytool.with_suffix(".exe").is_file() else Path("keytool")
    run([keytool, "-genkeypair", "-v", "-keystore", KEYSTORE,
         "-alias", KEY_ALIAS, "-keyalg", "RSA", "-keysize", "2048",
         "-validity", "10950", "-storepass", KEY_PASS, "-keypass", KEY_PASS,
         "-dname", "CN=Pipeline Notes, OU=private, O=pipeline, C=TH"],
        "สร้างกุญแจเซ็นชื่อใหม่")


def build(tools: dict) -> Path:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    for sub in ("res", "gen", "classes", "dex"):
        (BUILD / sub).mkdir(parents=True, exist_ok=True)

    run([tools["aapt2"], "compile", "--dir", HERE / "res",
         "-o", BUILD / "res.zip"], "แปลงไฟล์ res")

    run([tools["aapt2"], "link", "-o", BUILD / "base.apk",
         "-I", tools["android_jar"],
         "--manifest", HERE / "AndroidManifest.xml",
         "-R", BUILD / "res.zip",
         "--java", BUILD / "gen",
         "--min-sdk-version", MIN_SDK,
         "--target-sdk-version", TARGET_SDK,
         "--auto-add-overlay"], "ประกอบโครง apk")

    sources = [str(p) for p in (HERE / "java").rglob("*.java")]
    sources += [str(p) for p in (BUILD / "gen").rglob("*.java")]
    javac = Path(os.environ.get("JAVA_HOME", "")) / "bin" / "javac"
    javac = javac if javac.with_suffix(".exe").is_file() else Path("javac")
    # --release 8 ให้ใช้ได้กับ Android ทุกรุ่นที่รองรับ ส่วน android.* มาจาก classpath
    run([javac, "--release", "8", "-nowarn", "-encoding", "UTF-8",
         "-cp", tools["android_jar"], "-d", BUILD / "classes", *sources],
        "แปลโค้ด Java")

    classes = [str(p) for p in (BUILD / "classes").rglob("*.class")]
    run([tools["d8"], "--lib", tools["android_jar"], "--min-api", MIN_SDK,
         "--output", BUILD / "dex", *classes], "แปลงเป็น dex")

    unsigned = BUILD / "unsigned.apk"
    shutil.copy2(BUILD / "base.apk", unsigned)
    with zipfile.ZipFile(unsigned, "a", zipfile.ZIP_DEFLATED) as zf:
        zf.write(BUILD / "dex" / "classes.dex", "classes.dex")
    print("✅ ยัด classes.dex เข้า apk")

    aligned = BUILD / "aligned.apk"
    run([tools["zipalign"], "-f", "-p", "4", unsigned, aligned], "จัดแถวไฟล์ใน apk")

    final = BUILD / "notes.apk"
    shutil.copy2(aligned, final)
    run([tools["apksigner"], "sign", "--ks", KEYSTORE,
         "--ks-key-alias", KEY_ALIAS, "--ks-pass", f"pass:{KEY_PASS}",
         "--key-pass", f"pass:{KEY_PASS}", "--v1-signing-enabled", "true",
         "--v2-signing-enabled", "true", final], "เซ็นชื่อ apk")
    run([tools["apksigner"], "verify", "--print-certs", final], "ตรวจลายเซ็น")
    return final


def install(apk: Path, serial: str | None) -> None:
    if not ADB.is_file():
        die(f"ไม่เจอ adb ที่ {ADB}")
    args = [ADB]
    if serial:
        args += ["-s", serial]
    listing = subprocess.run([str(ADB), "devices"], capture_output=True, text=True,
                             creationflags=NO_WINDOW)
    print("\nเครื่องที่ต่ออยู่:\n" + (listing.stdout or "").strip())
    run(args + ["install", "-r", apk], "ติดตั้งลงเครื่อง")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true", help="ลงเครื่องหลังประกอบเสร็จ")
    parser.add_argument("--serial", default=None, help="ลงเครื่องไหน (ไม่ใส่ = เครื่องเดียวที่ต่ออยู่)")
    args = parser.parse_args()

    tools = find_tools()
    ensure_key()
    apk = build(tools)
    size = apk.stat().st_size / 1024
    print(f"\n📦 ได้ไฟล์แล้ว: {apk}  ({size:.0f} KB)")
    if args.install:
        install(apk, args.serial)
    return 0


if __name__ == "__main__":
    sys.exit(main())
