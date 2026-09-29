# -*- coding: utf-8 -*-
"""ประกอบ APK ของ Link Harvester แล้วลงเครื่องให้เลย — ปรับจาก android-notes/build.py

    python build.py                          ประกอบอย่างเดียว
    python build.py --install                ประกอบแล้วลงเครื่องที่ต่ออยู่
    python build.py --install --serial 93a21824

**ไม่ใช้ Gradle** แอปนี้พึ่งแค่ API ของ Android เอง (AccessibilityService) ไม่มีไลบรารีนอก
จึง build ด้วยชุดเครื่องมือเดียวกับ android-notes ได้ ต้องมี Android SDK build-tools + platform
(ตัวเดียวกับที่ build android-notes ผ่าน) และ JDK (javac, keytool)

กุญแจเซ็นชื่อเก็บที่ data/harvester/ ไม่เข้า git — หายแล้วอัปเดตทับไม่ได้ ต้องถอนแล้วลงใหม่
"""
import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDIO = HERE.parent
BUILD = HERE / "build"
SDK = Path(os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
           or Path.home() / "AppData/Local/Android/Sdk")

KEY_DIR = STUDIO / "data" / "harvester"
KEYSTORE = KEY_DIR / "harvester.jks"
KEY_ALIAS = "harvester"
KEY_PASS = "pipeline-harvester"       # แอปในวงส่วนตัว ไม่ได้ปล่อยขึ้นสโตร์
MIN_SDK, TARGET_SDK = "24", "34"
APK_NAME = "harvester.apk"

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def die(why):
    print(f"\n❌ {why}")
    sys.exit(1)


def run(args, why, **kw):
    done = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          creationflags=NO_WINDOW, **kw)
    if done.returncode:
        print(f"\n❌ {why} ไม่ผ่าน (รหัส {done.returncode})")
        print("   คำสั่ง:", " ".join(str(a) for a in args)[:400])
        if (done.stdout or "").strip():
            print("   ออกมาว่า:", done.stdout.strip()[:1500])
        if (done.stderr or "").strip():
            print("   ผิดพลาด:", done.stderr.strip()[:1500])
        sys.exit(1)
    print(f"✅ {why}")
    return done


def newest(folder, pattern="*"):
    hits = sorted(folder.glob(pattern)) if folder.is_dir() else []
    return hits[-1] if hits else None


def find_adb():
    """หา adb จาก: ตัวแปร ADB_PATH → SDK/platform-tools → โฟลเดอร์ tools ของโปรเจกต์ → PATH"""
    exe = ".exe" if os.name == "nt" else ""
    for cand in (os.environ.get("ADB_PATH", ""),
                 SDK / "platform-tools" / f"adb{exe}",
                 HERE / "tools" / f"adb{exe}",
                 STUDIO / "adb-mcp" / "tools" / f"adb{exe}"):
        if cand and Path(cand).is_file():
            return str(cand)
    return shutil.which("adb")


def find_tools():
    if not SDK.is_dir():
        die(f"ไม่มีชุดเครื่องมือ Android ที่ {SDK}\n"
            "   ตั้ง ANDROID_HOME ให้ชี้ไปที่ Android SDK (ตัวเดียวกับที่ build android-notes)")
    tools_dir = newest(SDK / "build-tools")
    if tools_dir is None:
        die(f'ไม่มี build-tools ใน {SDK} — สั่ง: sdkmanager "build-tools;34.0.0"')
    android_jar = None
    for plat in sorted((SDK / "platforms").glob("android-*"), reverse=True):
        if (plat / "android.jar").is_file():
            android_jar = plat / "android.jar"
            break
    if android_jar is None:
        die(f'ไม่มี android.jar — สั่ง: sdkmanager "platforms;android-34"')

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


def ensure_key():
    if KEYSTORE.is_file():
        print(f"ใช้กุญแจเดิมที่ {KEYSTORE}")
        return
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    keytool = Path(os.environ.get("JAVA_HOME", "")) / "bin" / "keytool"
    keytool = keytool if keytool.with_suffix(".exe").is_file() else Path("keytool")
    run([keytool, "-genkeypair", "-v", "-keystore", KEYSTORE,
         "-alias", KEY_ALIAS, "-keyalg", "RSA", "-keysize", "2048",
         "-validity", "10950", "-storepass", KEY_PASS, "-keypass", KEY_PASS,
         "-dname", "CN=Link Harvester, OU=private, O=pipeline, C=TH"],
        "สร้างกุญแจเซ็นชื่อใหม่")


def build(tools):
    if BUILD.exists():
        shutil.rmtree(BUILD)
    for sub in ("gen", "classes", "dex"):
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

    final = BUILD / APK_NAME
    shutil.copy2(aligned, final)
    run([tools["apksigner"], "sign", "--ks", KEYSTORE,
         "--ks-key-alias", KEY_ALIAS, "--ks-pass", f"pass:{KEY_PASS}",
         "--key-pass", f"pass:{KEY_PASS}", "--v1-signing-enabled", "true",
         "--v2-signing-enabled", "true", final], "เซ็นชื่อ apk")
    run([tools["apksigner"], "verify", "--print-certs", final], "ตรวจลายเซ็น")
    return final


def install(apk, serial):
    adb = find_adb()
    if not adb:
        die("ไม่เจอ adb — ตั้ง ADB_PATH หรือใส่ platform-tools ไว้ใน PATH")
    args = [adb] + (["-s", serial] if serial else [])
    listing = subprocess.run([adb, "devices"], capture_output=True, text=True,
                             creationflags=NO_WINDOW)
    print("\nเครื่องที่ต่ออยู่:\n" + (listing.stdout or "").strip())
    run(args + ["install", "-r", apk], "ติดตั้งลงเครื่อง")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--serial", default=None)
    args = parser.parse_args()

    tools = find_tools()
    ensure_key()
    apk = build(tools)
    print(f"\n📦 ได้ไฟล์แล้ว: {apk}  ({apk.stat().st_size / 1024:.0f} KB)")
    if args.install:
        install(apk, args.serial)
    return 0


if __name__ == "__main__":
    sys.exit(main())
