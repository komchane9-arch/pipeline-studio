package th.pipeline.harvest;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.util.List;

import rikka.shizuku.Shizuku;

/** หน้าหลัก — คุมการดักคลิปบอร์ดและดูลิงก์ที่เก็บได้ (แนว clippipe) */
public class MainActivity extends Activity {

    private static final int REQ_SHIZUKU = 1001;

    private Store store;
    private TextView status, list;
    private EditText keywords, forwardUrl, pollMs;

    private final Shizuku.OnRequestPermissionResultListener permListener =
            (requestCode, grantResult) -> refresh();

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        store = new Store(this);

        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 1);
        }
        try { Shizuku.addRequestPermissionResultListener(permListener); } catch (Throwable ignore) {}

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(16);
        root.setPadding(pad, pad, pad, pad);

        title(root, "ClipHarvest");
        hint(root, "ดักลิงก์ Shopee/Lazada จากคลิปบอร์ด แล้วเก็บ/ส่งต่อ (แนวเดียวกับ clippipe)");

        status = new TextView(this);
        status.setPadding(0, dp(8), 0, dp(8));
        root.addView(status);

        Button shizuku = btn("ขอสิทธิ์ Shizuku", v -> requestShizuku());
        root.addView(shizuku);

        LinearLayout runRow = new LinearLayout(this);
        runRow.setOrientation(LinearLayout.HORIZONTAL);
        runRow.addView(btn("▶ เริ่มดักจับ", v -> startCapture()), eq());
        runRow.addView(btn("■ หยุด", v -> stopCapture()), eq());
        root.addView(runRow);

        label(root, "เก็บเฉพาะข้อความที่มีคำ (คั่นด้วย , — ว่าง = เก็บทุกอย่าง)");
        keywords = field(store.keywordsRaw(), false);
        root.addView(keywords);

        label(root, "ส่งลิงก์ไปที่ URL (ว่าง = เก็บในเครื่องอย่างเดียว)");
        forwardUrl = field(store.forwardUrl(), false);
        forwardUrl.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        root.addView(forwardUrl);

        label(root, "ตรวจคลิปบอร์ดทุกกี่มิลลิวินาที");
        pollMs = field(String.valueOf(store.pollMs()), true);
        root.addView(pollMs);

        root.addView(btn("บันทึกการตั้งค่า", v -> saveConfig()));

        LinearLayout listRow = new LinearLayout(this);
        listRow.setOrientation(LinearLayout.HORIZONTAL);
        listRow.addView(btn("คัดลอกทั้งหมด", v -> copyAll()), eq());
        listRow.addView(btn("ล้างประวัติ", v -> { store.clear(); refresh(); }), eq());
        root.addView(listRow);

        list = new TextView(this);
        list.setPadding(0, dp(10), 0, 0);
        list.setTextIsSelectable(true);
        list.setTextSize(12);
        root.addView(list);

        ScrollView sv = new ScrollView(this);
        sv.addView(root);
        setContentView(sv);
        refresh();
    }

    @Override protected void onResume() { super.onResume(); refresh(); }

    @Override protected void onDestroy() {
        try { Shizuku.removeRequestPermissionResultListener(permListener); } catch (Throwable ignore) {}
        super.onDestroy();
    }

    // ---- Shizuku ----

    private boolean shizukuReady() {
        try {
            return Shizuku.pingBinder() && Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED;
        } catch (Throwable t) { return false; }
    }

    private void requestShizuku() {
        try {
            if (!Shizuku.pingBinder()) {
                toast("ยังไม่ได้เปิด Shizuku — เปิดแอป Shizuku แล้วสั่ง Start ก่อน");
                return;
            }
            if (Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED) {
                toast("ได้สิทธิ์ Shizuku แล้ว");
                refresh();
                return;
            }
            if (Shizuku.shouldShowRequestPermissionRationale()) {
                toast("เคยปฏิเสธสิทธิ์ไว้ — ไปเปิดให้ในแอป Shizuku");
                return;
            }
            Shizuku.requestPermission(REQ_SHIZUKU);
        } catch (Throwable t) {
            toast("เรียก Shizuku ไม่ได้: " + t.getClass().getSimpleName());
        }
    }

    // ---- capture ----

    private void startCapture() {
        if (!shizukuReady()) { toast("ยังไม่พร้อม — ขอสิทธิ์ Shizuku ก่อน"); return; }
        saveConfig();
        Intent i = new Intent(this, CaptureService.class).setAction(CaptureService.ACTION_START);
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(i); else startService(i);
        toast("เริ่มดักจับแล้ว");
        refresh();
    }

    private void stopCapture() {
        startService(new Intent(this, CaptureService.class).setAction(CaptureService.ACTION_STOP));
        toast("สั่งหยุดแล้ว");
        refresh();
    }

    private void saveConfig() {
        int ms;
        try { ms = Integer.parseInt(pollMs.getText().toString().trim()); }
        catch (Exception e) { ms = 900; }
        store.saveConfig(keywords.getText().toString(), forwardUrl.getText().toString(), ms);
    }

    private void copyAll() {
        List<String> all = store.links();
        if (all.isEmpty()) { toast("ยังไม่มีลิงก์"); return; }
        ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        cm.setPrimaryClip(ClipData.newPlainText("links", android.text.TextUtils.join("\n", all)));
        toast("คัดลอก " + all.size() + " ลิงก์แล้ว");
    }

    private void refresh() {
        boolean ready = shizukuReady();
        boolean running = store.running();
        status.setText("Shizuku: " + (ready ? "พร้อม ✓" : "ยังไม่พร้อม ✗")
                + "   ·   สถานะ: " + (running ? "กำลังดักจับ" : "หยุดอยู่")
                + "\nเก็บแล้ว " + store.count() + " ลิงก์");
        status.setTextColor(ready ? Color.parseColor("#1a7f37") : Color.parseColor("#cf222e"));
        List<String> all = store.links();
        StringBuilder sb = new StringBuilder();
        for (int i = all.size() - 1; i >= 0 && sb.length() < 16000; i--) {
            sb.append(all.size() - i).append(". ").append(all.get(i)).append("\n\n");
        }
        list.setText(sb.length() == 0 ? "(ยังไม่มีลิงก์ที่เก็บได้)" : sb.toString());
    }

    // ---- ตัวช่วย UI ----

    private Button btn(String text, View.OnClickListener onClick) {
        Button b = new Button(this);
        b.setText(text);
        b.setOnClickListener(onClick);
        return b;
    }

    private EditText field(String value, boolean number) {
        EditText e = new EditText(this);
        e.setInputType(number ? InputType.TYPE_CLASS_NUMBER
                : InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        e.setText(value);
        return e;
    }

    private void title(LinearLayout p, String s) {
        TextView t = new TextView(this);
        t.setText(s); t.setTextSize(22); t.setTextColor(Color.BLACK);
        p.addView(t);
    }

    private void label(LinearLayout p, String s) {
        TextView t = new TextView(this);
        t.setText(s); t.setPadding(0, dp(12), 0, dp(4)); t.setTextColor(Color.DKGRAY);
        p.addView(t);
    }

    private void hint(LinearLayout p, String s) {
        TextView t = new TextView(this);
        t.setText(s); t.setTextSize(12); t.setTextColor(Color.GRAY); t.setPadding(0, dp(4), 0, dp(4));
        p.addView(t);
    }

    private LinearLayout.LayoutParams eq() {
        return new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
    }

    private int dp(int v) { return Math.round(v * getResources().getDisplayMetrics().density); }

    private void toast(String s) { Toast.makeText(this, s, Toast.LENGTH_SHORT).show(); }
}
