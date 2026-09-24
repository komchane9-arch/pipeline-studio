"""build_and_install_remote_apk.py — ประกอบ APK และติดตั้งลงมือถือ Xiaomi ทันที

ไม่ต้องพึ่งพา Android Studio หรือ Gradle — ใช้ toolchain ภายในระบบ
คอมไพล์เป็น native Android WebView Application (.apk) และติดตั้งลงเครื่องผ่าน ADB
"""

import os
import shutil
import subprocess
import sys
import zipfile

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, "remote-app")
TOOLCHAIN_DIR = r"C:\project\2.Auto gen Video\7.web app\android-app\.toolchain"
AAPT2 = os.path.join(TOOLCHAIN_DIR, "android-14", "aapt2.exe")
ZIPALIGN = os.path.join(TOOLCHAIN_DIR, "android-14", "zipalign.exe")
D8_JAR = os.path.join(TOOLCHAIN_DIR, "android-14", "lib", "d8.jar")
APKSIGNER_JAR = os.path.join(TOOLCHAIN_DIR, "android-14", "lib", "apksigner.jar")
ANDROID_JAR = os.path.join(TOOLCHAIN_DIR, "android-34", "android.jar")
KEYSTORE = r"C:\project\2.Auto gen Video\7.web app\android-app\debug.keystore"

JAVA_BIN = r"C:\Program Files\Eclipse Adoptium\jdk-17.0.20.8-hotspot\bin"
JAVAC = os.path.join(JAVA_BIN, "javac.exe")
JAVA = os.path.join(JAVA_BIN, "java.exe")

TARGET_SERIAL = "93a21824"

def run(cmd, cwd=None):
    cmd_str = " ".join(f'"{c}"' if " " in c else c for c in cmd)
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace")
    if p.returncode != 0:
        print(f"❌ ล้มเหลวในคำสั่ง: {cmd_str}")
        if p.stdout:
            print("STDOUT:\n", p.stdout)
        if p.stderr:
            print("STDERR:\n", p.stderr)
        sys.exit(1)
    return p.stdout

def build_apk():
    print("=== [1/6] ล้างโฟลเดอร์ build และเตรียมโครงสร้าง ===")
    build_dir = os.path.join(APP_DIR, "build")
    dist_dir = os.path.join(APP_DIR, "dist")
    gen_dir = os.path.join(build_dir, "gen")
    classes_dir = os.path.join(build_dir, "classes")
    dex_dir = os.path.join(build_dir, "dex")

    shutil.rmtree(build_dir, ignore_errors=True)
    shutil.rmtree(dist_dir, ignore_errors=True)
    os.makedirs(gen_dir, exist_ok=True)
    os.makedirs(classes_dir, exist_ok=True)
    os.makedirs(dex_dir, exist_ok=True)
    os.makedirs(dist_dir, exist_ok=True)

    print("=== [2/6] aapt2: รวมทรัพยากร + AndroidManifest ===")
    res_flata = os.path.join(build_dir, "res.flata")
    run([AAPT2, "compile", "--dir", os.path.join(APP_DIR, "res"), "-o", res_flata], cwd=APP_DIR)
    
    base_apk = os.path.join(build_dir, "base.apk")
    manifest = os.path.join(APP_DIR, "AndroidManifest.xml")
    run([
        AAPT2, "link",
        "-I", ANDROID_JAR,
        "--manifest", manifest,
        "--java", gen_dir,
        "--auto-add-overlay",
        "-o", base_apk,
        res_flata
    ], cwd=APP_DIR)

    print("=== [3/6] javac: คอมไพล์โค้ด Java เป็น .class ===")
    r_java = os.path.join(gen_dir, "th", "pipeline", "remote", "R.java")
    main_java = os.path.join(APP_DIR, "src", "th", "pipeline", "remote", "MainActivity.java")
    run([
        JAVAC, "--release", "8", "-nowarn", "-encoding", "UTF-8",
        "-cp", ANDROID_JAR,
        "-d", classes_dir,
        r_java, main_java
    ], cwd=APP_DIR)

    print("=== [4/6] d8: แปลง bytecode เป็น Dalvik classes.dex ===")
    class_files = []
    for root, _, files in os.walk(classes_dir):
        for f in files:
            if f.endswith(".class"):
                class_files.append(os.path.join(root, f))
    
    run([
        JAVA, "-cp", D8_JAR, "com.android.tools.r8.D8",
        "--release",
        "--lib", ANDROID_JAR,
        "--output", dex_dir,
        *class_files
    ], cwd=APP_DIR)

    print("=== [5/6] รวม classes.dex เข้า base.apk ===")
    dex_file = os.path.join(dex_dir, "classes.dex")
    with zipfile.ZipFile(base_apk, "a", zipfile.ZIP_DEFLATED) as apk:
        apk.write(dex_file, "classes.dex")

    print("=== [6/6] zipalign + ลงลายเซ็น (apksigner) ===")
    aligned_apk = os.path.join(build_dir, "aligned.apk")
    run([ZIPALIGN, "-f", "4", base_apk, aligned_apk], cwd=APP_DIR)

    final_apk = os.path.join(dist_dir, "pipeline-remote.apk")
    run([
        JAVA, "-jar", APKSIGNER_JAR, "sign",
        "--ks", KEYSTORE,
        "--ks-pass", "pass:android",
        "--key-pass", "pass:android",
        "--out", final_apk,
        aligned_apk
    ], cwd=APP_DIR)

    print(f"✅ คอมไพล์ APK สำเร็จ: {final_apk} ({os.path.getsize(final_apk):,} bytes)")
    return final_apk

def install_and_launch(apk_path, serial):
    print(f"\n=== เริ่มติดตั้งแอปพลิเคชันลงใน Xiaomi [{serial}] ===")
    
    # 1. Reverse port
    print("• ตั้งค่า adb reverse (tcp:8866 -> tcp:8866)...")
    subprocess.run(["adb", "-s", serial, "reverse", "tcp:8866", "tcp:8866"], check=False)
    
    # 2. Install APK
    print("• กำลังส่งและติดตั้ง APK เข้ามือถือ...")
    p = subprocess.run(["adb", "-s", serial, "install", "-r", apk_path], capture_output=True, text=True, errors="replace")
    if p.returncode == 0 and "Success" in p.stdout:
        print("✅ ติดตั้งแอปพลิเคชันสำเร็จ 100%!")
    else:
        print(f"ผลการติดตั้ง:\n{p.stdout}\n{p.stderr}")
        if "INSTALL_FAILED" in (p.stdout + p.stderr):
            print("⚠️ หากติดข้อจำกัด MIUI Install via USB: ให้เปิดตัวเลือก 'ติดตั้งผ่าน USB' ใน Developer options บนมือถือ")

    # 3. Launch App
    print("• กำลังสั่งเปิดแอปพลิเคชัน Pipeline Remote บนหน้าจอมือถือ...")
    run_cmd = ["adb", "-s", serial, "shell", "am", "start", "-n", "th.pipeline.remote/.MainActivity"]
    launch_res = subprocess.run(run_cmd, capture_output=True, text=True, errors="replace")
    print(launch_res.stdout.strip())

    print("\n" + "="*60)
    print("🎉 แอปพลิเคชัน Pipeline Remote ติดตั้งและเปิดใช้งานเรียบร้อยแล้ว!")
    print("="*60)
    print("📱 ตรวจสอบที่หน้าจอมือถือ Xiaomi จะเห็นแอปชื่อ 'Pipeline Remote'")
    print("พร้อมใช้งานรีโมทควบคุมมือถือทุกเครื่องแบบเต็มหน้าจอทันที!")
    print("="*60)

if __name__ == "__main__":
    serial = sys.argv[1] if len(sys.argv) > 1 else TARGET_SERIAL
    apk = build_apk()
    install_and_launch(apk, serial)
