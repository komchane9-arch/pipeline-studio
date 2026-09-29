package th.pipeline.harvest;

import android.content.ClipData;
import android.content.Context;
import android.os.IBinder;

import java.lang.reflect.Method;

import rikka.shizuku.Shizuku;
import rikka.shizuku.ShizukuBinderWrapper;
import rikka.shizuku.SystemServiceHelper;

/**
 * อ่าน/เขียนคลิปบอร์ดของเครื่องผ่าน Shizuku (สิทธิ์ระดับ shell)
 *
 * - read: ใช้เก็บลิงก์หลังกด "คัดลอกลิงก์" ในแอป Shopee/Lazada
 * - setText: ใช้ตั้งคลิปบอร์ดเป็น keyword แล้ว paste เข้าช่องค้นหา (รองรับภาษาไทย)
 *
 * ใช้ reflection เพราะเมธอด getPrimaryClip/setPrimaryClip เปลี่ยนพารามิเตอร์ทุกเวอร์ชัน Android
 */
public class ClipReader {

    private static final String SHELL_PKG = "com.android.shell";

    private final Object clipboard;   // android.content.IClipboard
    private final Method getPrimaryClip;
    private final Method setPrimaryClip;

    public ClipReader() throws Exception {
        IBinder raw = SystemServiceHelper.getSystemService(Context.CLIPBOARD_SERVICE);
        if (raw == null) throw new IllegalStateException("ไม่พบ service clipboard");
        IBinder binder = new ShizukuBinderWrapper(raw);
        Class<?> stub = Class.forName("android.content.IClipboard$Stub");
        clipboard = stub.getMethod("asInterface", IBinder.class).invoke(null, binder);

        Class<?> iface = Class.forName("android.content.IClipboard");
        getPrimaryClip = widest(iface, "getPrimaryClip");
        setPrimaryClip = widest(iface, "setPrimaryClip");
    }

    private static Method widest(Class<?> iface, String name) {
        Method pick = null;
        for (Method m : iface.getMethods()) {
            if (m.getName().equals(name)
                    && (pick == null || m.getParameterTypes().length > pick.getParameterTypes().length)) {
                pick = m;
            }
        }
        return pick;
    }

    public boolean available() {
        return Shizuku.pingBinder() && Shizuku.checkSelfPermission() == 0;
    }

    /** อ่านข้อความในคลิปบอร์ด — "" ถ้าไม่มี/อ่านไม่ได้ */
    public String read(Context ctx) {
        try {
            Object clip = getPrimaryClip.invoke(clipboard,
                    args(getPrimaryClip.getParameterTypes(), null));
            if (!(clip instanceof ClipData)) return "";
            ClipData data = (ClipData) clip;
            if (data.getItemCount() == 0) return "";
            CharSequence t = data.getItemAt(0).coerceToText(ctx);
            return t == null ? "" : t.toString();
        } catch (Throwable t) {
            return "";
        }
    }

    /** ตั้งคลิปบอร์ดเป็นข้อความ */
    public boolean setText(String text) {
        try {
            ClipData clip = ClipData.newPlainText("kw", text);
            setPrimaryClip.invoke(clipboard, args(setPrimaryClip.getParameterTypes(), clip));
            return true;
        } catch (Throwable t) {
            return false;
        }
    }

    /**
     * เติมค่าพารามิเตอร์ตามชนิด: ClipData = clip, String แรก = ชื่อแพ็กเกจ shell,
     * String อื่น = null, int = 0 (userId/deviceId ใช้ค่า default)
     */
    private Object[] args(Class<?>[] types, ClipData clip) {
        Object[] a = new Object[types.length];
        boolean firstString = true;
        for (int i = 0; i < types.length; i++) {
            Class<?> t = types[i];
            if (t == ClipData.class) a[i] = clip;
            else if (t == String.class) { a[i] = firstString ? SHELL_PKG : null; firstString = false; }
            else if (t == int.class || t == Integer.class) a[i] = 0;
            else a[i] = null;
        }
        return a;
    }
}
