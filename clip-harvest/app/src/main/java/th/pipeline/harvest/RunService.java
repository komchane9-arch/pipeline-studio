package th.pipeline.harvest;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

/**
 * ปุ่มลอยบนหน้าจอ — เริ่ม / หยุด / ลบ  และรันงานขับ Shopee/Lazada ในเธรดพื้นหลัง
 *
 * กด "เริ่มทำงาน" ในหน้าหลัก → มาที่นี่ → โชว์ปุ่มลอย ค้างทับทุกแอป
 * กดเริ่มบนปุ่มลอย → เริ่มไล่ค้นหา/เก็บลิงก์  ·  หยุด → หยุดกลางคัน  ·  ลบ → ล้างลิงก์ที่เก็บ
 */
public class RunService extends Service {

    public static boolean ALIVE = false;
    private static final String CHANNEL = "run";
    private static final int NOTI_ID = 9;

    private WindowManager wm;
    private View overlay;
    private TextView statusView;
    private Store store;
    private Thread worker;
    private volatile Automation current;
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override public void onCreate() {
        super.onCreate();
        store = new Store(this);
        startForeground(NOTI_ID, notif("พร้อม — กดเริ่มบนปุ่มลอย"));
        showOverlay();
        ALIVE = true;
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) { return START_STICKY; }

    // ---- ปุ่มลอย ----

    private void showOverlay() {
        wm = (WindowManager) getSystemService(WINDOW_SERVICE);
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackgroundColor(Color.parseColor("#EE222222"));
        int p = dp(6);
        box.setPadding(p, p, p, p);

        statusView = new TextView(this);
        statusView.setTextColor(Color.WHITE);
        statusView.setTextSize(11);
        statusView.setText("หยุดอยู่ · เก็บ " + store.count());
        box.addView(statusView);

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.addView(mini("▶ เริ่ม", v -> startRun()));
        row.addView(mini("■ หยุด", v -> stopRun()));
        row.addView(mini("🗑 ลบ", v -> { store.clear(); toast("ล้างลิงก์แล้ว"); refresh(); }));
        row.addView(mini("✕", v -> stopSelf()));
        box.addView(row);

        WindowManager.LayoutParams lp = new WindowManager.LayoutParams(
                WindowManager.LayoutParams.WRAP_CONTENT,
                WindowManager.LayoutParams.WRAP_CONTENT,
                Build.VERSION.SDK_INT >= 26
                        ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                        : WindowManager.LayoutParams.TYPE_PHONE,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
                PixelFormat.TRANSLUCENT);
        lp.gravity = Gravity.TOP | Gravity.START;
        lp.x = dp(8); lp.y = dp(120);
        makeDraggable(box, lp);
        overlay = box;
        wm.addView(overlay, lp);
    }

    private Button mini(String text, View.OnClickListener onClick) {
        Button b = new Button(this);
        b.setText(text);
        b.setAllCaps(false);
        b.setTextSize(11);
        b.setPadding(dp(6), dp(2), dp(6), dp(2));
        b.setOnClickListener(onClick);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.rightMargin = dp(4);
        b.setLayoutParams(lp);
        return b;
    }

    private void makeDraggable(View v, WindowManager.LayoutParams lp) {
        v.setOnTouchListener(new View.OnTouchListener() {
            int sx, sy; float tx, ty;
            @Override public boolean onTouch(View view, MotionEvent e) {
                switch (e.getAction()) {
                    case MotionEvent.ACTION_DOWN:
                        sx = lp.x; sy = lp.y; tx = e.getRawX(); ty = e.getRawY(); return false;
                    case MotionEvent.ACTION_MOVE:
                        lp.x = sx + (int) (e.getRawX() - tx);
                        lp.y = sy + (int) (e.getRawY() - ty);
                        wm.updateViewLayout(overlay, lp); return false;
                }
                return false;
            }
        });
    }

    // ---- คุมงาน ----

    private void startRun() {
        if (worker != null && worker.isAlive()) { toast("กำลังทำงานอยู่"); return; }
        ClipReader clip;
        try { clip = new ClipReader(); }
        catch (Throwable t) { toast("Shizuku ไม่พร้อม"); store.log("เริ่มไม่ได้: Shizuku ไม่พร้อม"); return; }
        if (!clip.available()) { toast("Shizuku ไม่พร้อม"); return; }

        store.setRunning(true);
        store.log("---- เริ่มทำงาน ----");
        current = new Automation(this, clip);
        worker = new Thread(() -> {
            try { current.run(); }
            catch (Throwable t) { store.log("งานล้ม: " + t); }
            finally {
                store.setRunning(false);
                ui.post(this::refresh);
            }
        }, "harvest-run");
        worker.start();
        refresh();
    }

    private void stopRun() {
        if (current != null) current.stop();
        store.setRunning(false);
        store.log("ผู้ใช้สั่งหยุด");
        toast("สั่งหยุดแล้ว");
        refresh();
    }

    private void refresh() {
        boolean running = store.running();
        String s = (running ? "กำลังทำงาน" : "หยุดอยู่") + " · เก็บ " + store.count();
        if (statusView != null) statusView.setText(s);
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm != null) nm.notify(NOTI_ID, notif(s));
    }

    private Notification notif(String text) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (Build.VERSION.SDK_INT >= 26 && nm != null) {
            nm.createNotificationChannel(new NotificationChannel(
                    CHANNEL, "ClipHarvest", NotificationManager.IMPORTANCE_LOW));
        }
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL) : new Notification.Builder(this);
        return b.setContentTitle("ClipHarvest").setContentText(text)
                .setSmallIcon(android.R.drawable.ic_menu_search).setOngoing(true).build();
    }

    private void toast(String s) { ui.post(() -> Toast.makeText(this, s, Toast.LENGTH_SHORT).show()); }
    private int dp(int v) { return Math.round(v * getResources().getDisplayMetrics().density); }

    @Override public IBinder onBind(Intent i) { return null; }

    @Override public void onDestroy() {
        ALIVE = false;
        if (current != null) current.stop();
        store.setRunning(false);
        if (overlay != null && wm != null) try { wm.removeView(overlay); } catch (Exception ignore) {}
        super.onDestroy();
    }
}
