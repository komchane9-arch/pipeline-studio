package th.pipeline.harvest;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;

/**
 * บริการเบื้องหลัง — คอยอ่านคลิปบอร์ดทุก ๆ pollMs แล้วเก็บลิงก์ที่เข้าเงื่อนไข
 *
 * รันเป็น foreground service (มีแจ้งเตือนค้าง) เพื่อไม่ให้ระบบฆ่าทิ้ง
 */
public class CaptureService extends Service {

    public static final String ACTION_START = "th.pipeline.harvest.START";
    public static final String ACTION_STOP = "th.pipeline.harvest.STOP";
    private static final String CHANNEL = "capture";
    private static final int NOTI_ID = 7;

    private HandlerThread thread;
    private Handler handler;
    private Store store;
    private ClipReader reader;
    private volatile boolean running;

    private final Runnable tick = new Runnable() {
        @Override public void run() {
            if (!running) return;
            poll();
            handler.postDelayed(this, Math.max(400, store.pollMs()));
        }
    };

    @Override public void onCreate() {
        super.onCreate();
        store = new Store(this);
        thread = new HandlerThread("clip-poll");
        thread.start();
        handler = new Handler(thread.getLooper());
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent != null ? intent.getAction() : ACTION_START;
        if (ACTION_STOP.equals(action)) {
            stopCapture();
            return START_NOT_STICKY;
        }
        startForeground(NOTI_ID, buildNotification("กำลังดักลิงก์… เก็บแล้ว " + store.count()));
        startCapture();
        return START_STICKY;
    }

    private void startCapture() {
        if (running) return;
        try {
            reader = new ClipReader();
        } catch (Throwable t) {
            update("เริ่มไม่ได้: Shizuku ยังไม่พร้อม (" + t.getClass().getSimpleName() + ")");
            store.setRunning(false);
            stopForeground(true);
            stopSelf();
            return;
        }
        running = true;
        store.setRunning(true);
        handler.post(tick);
    }

    private void stopCapture() {
        running = false;
        store.setRunning(false);
        handler.removeCallbacksAndMessages(null);
        stopForeground(true);
        stopSelf();
    }

    private void poll() {
        if (reader == null || !reader.available()) {
            update("Shizuku หลุด — หยุดชั่วคราว");
            return;
        }
        String text = reader.read(this).trim();
        if (text.isEmpty() || text.equals(store.lastSeen())) return;
        store.setLastSeen(text);
        if (!store.matches(text)) return;
        // ข้อความอาจมีลิงก์ปนข้อความ — เก็บทั้งก้อนแบบเดียวกับ clippipe (ปลายทางไปแยกเอง)
        if (store.add(text)) {
            final String forward = store.forwardUrl();
            if (!forward.isEmpty()) {
                new Thread(() -> Forwarder.post(forward, text)).start();
            }
            update("เก็บลิงก์ใหม่แล้ว · รวม " + store.count());
        }
    }

    private void update(String msg) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm != null) nm.notify(NOTI_ID, buildNotification(msg));
    }

    private Notification buildNotification(String text) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (Build.VERSION.SDK_INT >= 26 && nm != null) {
            nm.createNotificationChannel(new NotificationChannel(
                    CHANNEL, "ClipHarvest", NotificationManager.IMPORTANCE_LOW));
        }
        Intent open = new Intent(this, MainActivity.class);
        int flag = Build.VERSION.SDK_INT >= 31 ? PendingIntent.FLAG_IMMUTABLE : 0;
        PendingIntent pi = PendingIntent.getActivity(this, 0, open, flag);

        Intent stop = new Intent(this, CaptureService.class).setAction(ACTION_STOP);
        PendingIntent stopPi = PendingIntent.getService(this, 1, stop, flag);

        Notification.Builder b = (Build.VERSION.SDK_INT >= 26)
                ? new Notification.Builder(this, CHANNEL) : new Notification.Builder(this);
        return b.setContentTitle("ClipHarvest")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.ic_menu_save)
                .setContentIntent(pi)
                .setOngoing(true)
                .addAction(android.R.drawable.ic_menu_close_clear_cancel, "หยุด", stopPi)
                .build();
    }

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public void onDestroy() {
        running = false;
        if (thread != null) thread.quitSafely();
        super.onDestroy();
    }
}
