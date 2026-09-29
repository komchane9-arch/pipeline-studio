package th.pipeline.harvester;

import android.accessibilityservice.AccessibilityService;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Rect;
import android.os.Build;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.Toast;

import java.io.File;
import java.io.FileWriter;
import java.util.ArrayDeque;

/**
 * เครื่องยนต์อ่าน/กดหน้าจอแอปอื่น
 *
 * เวอร์ชันแรก: พิสูจน์ว่าอ่านหน้าจอ Shopee ได้ไหม — มีปุ่ม "Dump หน้าจอ" ในแจ้งเตือน
 * กดตอนเปิดหน้าค้นหา Shopee ค้างไว้ แล้วดูว่าอ่าน "EXTRA COMM" เจอกี่ใบ
 *
 * ทำไมอาจอ่านได้ทั้งที่ uiautomator อ่านไม่ได้: uiautomator รอให้จอ "นิ่ง" ก่อน dump
 * ซึ่ง Shopee มีอนิเมชันตลอดเลย timeout — ส่วน accessibility ดึง node สดจาก
 * getRootInActiveWindow() ไม่ต้องรอจอนิ่ง
 */
public class HarvestService extends AccessibilityService {

    public static HarvestService INSTANCE;
    private static final String CHANNEL = "harvester";
    private static final int NOTI_ID = 42;
    static final String ACTION_DUMP = "th.pipeline.harvester.DUMP";

    private final BroadcastReceiver receiver = new BroadcastReceiver() {
        @Override public void onReceive(Context c, Intent i) {
            if (ACTION_DUMP.equals(i.getAction())) dumpCurrentScreen();
        }
    };

    @Override
    protected void onServiceConnected() {
        INSTANCE = this;
        IntentFilter filter = new IntentFilter(ACTION_DUMP);
        // API 33+ บังคับระบุว่า receiver เปิดให้แอปอื่นยิงได้ไหม — เราใช้ภายในแอปเท่านั้น
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            registerReceiver(receiver, filter);
        }
        showNotification("พร้อมแล้ว — เปิดหน้าค้นหา Shopee แล้วกด ‘Dump หน้าจอ’");
    }

    @Override public void onAccessibilityEvent(AccessibilityEvent event) { /* v0.1 ยังไม่ใช้ */ }
    @Override public void onInterrupt() { }

    @Override public boolean onUnbind(Intent intent) {
        try { unregisterReceiver(receiver); } catch (Exception ignore) {}
        INSTANCE = null;
        return super.onUnbind(intent);
    }

    // ---------------------------------------------------------------- dump

    /** อ่านทั้งหน้าจอปัจจุบัน เก็บข้อความทุก node เขียนลงไฟล์ แล้วเด้ง toast สรุป */
    public void dumpCurrentScreen() {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) {
            toast("อ่านหน้าจอไม่ได้ (root = null) — แอปนี้อาจบล็อก accessibility");
            return;
        }
        StringBuilder sb = new StringBuilder();
        CharSequence pkg = root.getPackageName();
        sb.append("package=").append(pkg).append("\n");
        int[] count = {0};
        int[] extraComm = {0};

        ArrayDeque<AccessibilityNodeInfo> stack = new ArrayDeque<>();
        stack.push(root);
        while (!stack.isEmpty()) {
            AccessibilityNodeInfo n = stack.pop();
            if (n == null) continue;
            count[0]++;
            CharSequence text = n.getText();
            CharSequence desc = n.getContentDescription();
            String id = n.getViewIdResourceName();
            String label = text != null ? text.toString()
                    : desc != null ? desc.toString() : "";
            if (!label.isEmpty() || id != null) {
                Rect b = new Rect();
                n.getBoundsInScreen(b);
                String cls = String.valueOf(n.getClassName());
                cls = cls.substring(cls.lastIndexOf('.') + 1);
                sb.append(String.format("(%d,%d) %s%s%s [%s]%s\n",
                        b.centerX(), b.centerY(), cls,
                        id != null ? " id=" + id.substring(id.indexOf('/') + 1) : "",
                        n.isClickable() ? " C" : "",
                        label.length() > 80 ? label.substring(0, 80) : label,
                        n.isClickable() ? "" : ""));
                String low = label.toLowerCase();
                if (low.contains("extra comm") || low.contains("extracomm")) extraComm[0]++;
            }
            for (int i = 0; i < n.getChildCount(); i++) stack.push(n.getChild(i));
        }

        String summary = "package " + pkg + " · อ่านได้ " + count[0]
                + " node · เจอ EXTRA COMM " + extraComm[0] + " จุด";
        sb.insert(0, summary + "\n\n");

        File out = new File(getExternalFilesDir(null), "dump.txt");
        try (FileWriter w = new FileWriter(out)) {
            w.write(sb.toString());
        } catch (Exception e) {
            toast("เขียนไฟล์ไม่ได้: " + e.getMessage());
            return;
        }
        toast(summary + "\nไฟล์: " + out.getAbsolutePath());
        showNotification(summary);
    }

    // ---------------------------------------------------------------- แจ้งเตือน

    private void showNotification(String text) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(new NotificationChannel(
                    CHANNEL, "Link Harvester", NotificationManager.IMPORTANCE_LOW));
        }
        Intent dump = new Intent(ACTION_DUMP).setPackage(getPackageName());
        int flag = Build.VERSION.SDK_INT >= 31 ? PendingIntent.FLAG_IMMUTABLE : 0;
        PendingIntent pi = PendingIntent.getBroadcast(this, 0, dump, flag);

        Notification.Builder b = (Build.VERSION.SDK_INT >= 26)
                ? new Notification.Builder(this, CHANNEL) : new Notification.Builder(this);
        Notification noti = b
                .setContentTitle("Link Harvester")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.ic_menu_search)
                .setOngoing(true)
                .addAction(android.R.drawable.ic_menu_view, "Dump หน้าจอ", pi)
                .build();
        nm.notify(NOTI_ID, noti);
    }

    private void toast(final String msg) {
        new android.os.Handler(getMainLooper()).post(() ->
                Toast.makeText(this, msg, Toast.LENGTH_LONG).show());
    }
}
