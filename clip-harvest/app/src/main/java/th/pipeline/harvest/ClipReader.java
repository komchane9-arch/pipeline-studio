package th.pipeline.harvest;

import android.content.ClipData;
import android.content.Context;
import android.os.IBinder;

import java.lang.reflect.Method;

import rikka.shizuku.Shizuku;
import rikka.shizuku.ShizukuBinderWrapper;
import rikka.shizuku.SystemServiceHelper;

/**
 * อ่านคลิปบอร์ดของเครื่องผ่าน Shizuku (สิทธิ์ระดับ shell)
 *
 * ทำไมต้องผ่าน Shizuku: ตั้งแต่ Android 10 แอปที่ไม่ได้อยู่หน้าจออ่านคลิปบอร์ดไม่ได้
 * Shizuku ให้เราเรียก system service `clipboard` ในนามของ shell ซึ่งอ่านได้
 *
 * ทำไมใช้ reflection: เมธอด getPrimaryClip ของ IClipboard เปลี่ยนพารามิเตอร์ทุกเวอร์ชัน Android
 * (เพิ่ม attributionTag ใน 13, deviceId ใน 14 ฯลฯ) — reflection ไล่เติมค่าตามชนิดพารามิเตอร์
 * จึงทนต่อการเปลี่ยนเวอร์ชันโดยไม่ต้องแก้โค้ด
 */
public class ClipReader {

    // เรียกในนามแพ็กเกจ shell ให้ตรงกับ UID ที่ Shizuku ใช้ ไม่งั้นโดน SecurityException
    private static final String SHELL_PKG = "com.android.shell";

    private final Object clipboard;   // android.content.IClipboard
    private final Method getPrimaryClip;

    public ClipReader() throws Exception {
        IBinder raw = SystemServiceHelper.getSystemService(Context.CLIPBOARD_SERVICE);
        if (raw == null) throw new IllegalStateException("ไม่พบ service clipboard");
        IBinder binder = new ShizukuBinderWrapper(raw);
        Class<?> stub = Class.forName("android.content.IClipboard$Stub");
        clipboard = stub.getMethod("asInterface", IBinder.class).invoke(null, binder);

        Method pick = null;
        for (Method m : Class.forName("android.content.IClipboard").getMethods()) {
            if (m.getName().equals("getPrimaryClip")) {
                if (pick == null || m.getParameterTypes().length > pick.getParameterTypes().length) {
                    pick = m; // เลือกตัวที่พารามิเตอร์มากสุด = เวอร์ชันใหม่สุดที่ framework รองรับ
                }
            }
        }
        if (pick == null) throw new NoSuchMethodException("IClipboard.getPrimaryClip");
        getPrimaryClip = pick;
    }

    public boolean available() {
        return Shizuku.pingBinder() && Shizuku.checkSelfPermission() == 0; // 0 = PERMISSION_GRANTED
    }

    /** อ่านข้อความในคลิปบอร์ด — คืน "" ถ้าไม่มี/อ่านไม่ได้ */
    public String read(Context ctx) {
        try {
            Object clip = getPrimaryClip.invoke(clipboard, buildArgs(getPrimaryClip.getParameterTypes()));
            if (!(clip instanceof ClipData)) return "";
            ClipData data = (ClipData) clip;
            if (data.getItemCount() == 0) return "";
            CharSequence text = data.getItemAt(0).coerceToText(ctx);
            return text == null ? "" : text.toString();
        } catch (Throwable t) {
            return "";
        }
    }

    /** เติมค่าให้แต่ละพารามิเตอร์ตามชนิด: String แรก = ชื่อแพ็กเกจ, String อื่น = null, int แรก = userId 0, int อื่น = 0 */
    private Object[] buildArgs(Class<?>[] types) {
        Object[] args = new Object[types.length];
        boolean firstString = true, firstInt = true;
        for (int i = 0; i < types.length; i++) {
            Class<?> t = types[i];
            if (t == String.class) {
                args[i] = firstString ? SHELL_PKG : null;
                firstString = false;
            } else if (t == int.class || t == Integer.class) {
                args[i] = 0;            // userId แรก, deviceId ถัดไป ล้วนใช้ 0 (ค่า default)
                firstInt = false;
            } else {
                args[i] = null;
            }
        }
        return args;
    }
}
