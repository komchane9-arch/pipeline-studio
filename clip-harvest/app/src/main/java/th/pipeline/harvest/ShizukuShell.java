package th.pipeline.harvest;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.lang.reflect.Method;

import rikka.shizuku.Shizuku;

/**
 * สั่ง shell command บนเครื่องผ่าน Shizuku (สิทธิ์ระดับ shell = เทียบเท่า adb)
 *
 * ใช้ Shizuku.newProcess ผ่าน reflection (เป็น API ที่ซ่อนไว้ แต่ใช้ได้จริง เหมือนที่แอปสาย
 * Shizuku ทั่วไปทำ) เพื่อรัน input/screencap โดยไม่ต้องต่อคอม
 */
public class ShizukuShell {

    private static Method newProcess;

    private static Method np() throws Exception {
        if (newProcess == null) {
            newProcess = Shizuku.class.getDeclaredMethod(
                    "newProcess", String[].class, String[].class, String.class);
            newProcess.setAccessible(true);
        }
        return newProcess;
    }

    public static boolean ready() {
        try { return Shizuku.pingBinder() && Shizuku.checkSelfPermission() == 0; }
        catch (Throwable t) { return false; }
    }

    private static Process run(String[] cmd) throws Exception {
        return (Process) np().invoke(null, cmd, null, null);
    }

    /** รันคำสั่งแล้วคืน stdout เป็นข้อความ (รอจนจบ) */
    public static String exec(String command) {
        try {
            Process p = run(new String[]{"sh", "-c", command});
            String out = readAll(p.getInputStream());
            p.waitFor();
            return out;
        } catch (Throwable t) {
            return "";
        }
    }

    /** แคปหน้าจอเป็น Bitmap (screencap -p ส่ง PNG ออก stdout) */
    public static Bitmap screencap() {
        try {
            Process p = run(new String[]{"sh", "-c", "screencap -p"});
            byte[] png = readAllBytes(p.getInputStream());
            p.waitFor();
            if (png.length < 8) return null;
            return BitmapFactory.decodeByteArray(png, 0, png.length);
        } catch (Throwable t) {
            return null;
        }
    }

    // ---- คำสั่งกดหน้าจอ ----
    public static void tap(int x, int y) { exec("input tap " + x + " " + y); }
    public static void swipe(int x1, int y1, int x2, int y2, int ms) {
        exec("input swipe " + x1 + " " + y1 + " " + x2 + " " + y2 + " " + ms);
    }
    public static void key(int keycode) { exec("input keyevent " + keycode); }
    public static void back() { key(4); }
    public static void home() { key(3); }
    /** พิมพ์ข้อความ ASCII (ช่องว่างแทนด้วย %s) — ภาษาไทยใช้ ClipReader.setText + paste แทน */
    public static void typeAscii(String text) {
        exec("input text " + text.replace(" ", "%s"));
    }
    /** เปิดแอปจาก package */
    public static void launch(String pkg) {
        exec("monkey -p " + pkg + " -c android.intent.category.LAUNCHER 1");
    }
    public static void forceStop(String pkg) { exec("am force-stop " + pkg); }

    // ---- อ่าน stream ----
    private static String readAll(InputStream in) throws Exception {
        return new String(readAllBytes(in), "UTF-8");
    }

    private static byte[] readAllBytes(InputStream in) throws Exception {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
        in.close();
        return bos.toByteArray();
    }
}
