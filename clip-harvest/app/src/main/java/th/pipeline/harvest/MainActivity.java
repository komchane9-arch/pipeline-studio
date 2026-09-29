package th.pipeline.harvest;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.text.InputType;
import android.view.View;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import rikka.shizuku.Shizuku;

/** หน้าหลัก — ตั้ง keyword, เลือกแพลตฟอร์ม/โหมด, แล้วกดเริ่ม (ไปโผล่เป็นปุ่มลอย) */
public class MainActivity extends Activity {

    private static final int REQ_SHIZUKU = 1001, REQ_OVERLAY = 1002;

    private Store store;
    private EditText keyword;
    private CheckBox shopee, lazada;
    private LinearLayout shopeeModeBox;
    private RadioGroup shopeeMode;
    private RadioButton modeExtra, modeAll;
    private TextView status, links, log;

    private final Shizuku.OnRequestPermissionResultListener permListener =
            (code, grant) -> refresh();

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
        hint(root, "ใส่ keyword แล้วให้แอปไล่ค้น Shopee/Lazada เก็บลิงก์สินค้าให้เอง");

        status = new TextView(this);
        status.setPadding(0, dp(8), 0, dp(8));
        root.addView(status);
        root.addView(btn("ขอสิทธิ์ Shizuku", v -> requestShizuku()));

        label(root, "Keyword ที่จะค้นหา");
        keyword = new EditText(this);
        keyword.setInputType(InputType.TYPE_CLASS_TEXT);
        keyword.setHint("เช่น ถุงคลุมรถ");
        keyword.setText(store.keyword());
        root.addView(keyword);

        shopee = new CheckBox(this);
        shopee.setText("Shopee");
        shopee.setChecked(store.doShopee());
        shopee.setOnCheckedChangeListener((v, c) -> updateShopeeModeVisibility());
        root.addView(shopee);

        // กล่องตัวเลือกโหมด Shopee — โชว์เฉพาะเมื่อติ๊ก Shopee
        shopeeModeBox = new LinearLayout(this);
        shopeeModeBox.setOrientation(LinearLayout.VERTICAL);
        shopeeModeBox.setPadding(dp(24), 0, 0, 0);
        label(shopeeModeBox, "สินค้า Shopee ที่จะเก็บ (เลือกอย่างใดอย่างหนึ่ง)");
        shopeeMode = new RadioGroup(this);
        modeExtra = new RadioButton(this); modeExtra.setText("เอาแค่ EXTRA COMM");
        modeAll = new RadioButton(this); modeAll.setText("เอาทั้งหมด");
        shopeeMode.addView(modeExtra);
        shopeeMode.addView(modeAll);
        if (Store.MODE_ALL.equals(store.shopeeMode())) modeAll.setChecked(true); else modeExtra.setChecked(true);
        shopeeModeBox.addView(shopeeMode);
        root.addView(shopeeModeBox);

        lazada = new CheckBox(this);
        lazada.setText("Lazada (เก็บทุกลิงก์ที่ค้นเจอ)");
        lazada.setChecked(store.doLazada());
        root.addView(lazada);

        root.addView(btn("▶ เริ่มทำงาน (ไปเป็นปุ่มลอย)", v -> start()));
        hint(root, "ตอนทำงานจะมีปุ่มลอยให้กด เริ่ม / หยุด / ลบ — ถ้าติ๊กทั้งสองจะทำ Shopee ก่อน แล้วเว้น ~1-2 นาทีค่อยทำ Lazada");

        LinearLayout tools = new LinearLayout(this);
        tools.setOrientation(LinearLayout.HORIZONTAL);
        tools.addView(btn("ล้างลิงก์", v -> { store.clear(); refresh(); }), eq());
        tools.addView(btn("ล้าง log", v -> { store.clearLog(); refresh(); }), eq());
        root.addView(tools);

        label(root, "ลิงก์ที่เก็บได้");
        links = new TextView(this); links.setTextIsSelectable(true); links.setTextSize(12);
        root.addView(links);
        label(root, "บันทึกการทำงาน (log)");
        log = new TextView(this); log.setTextIsSelectable(true); log.setTextSize(11); log.setTextColor(Color.DKGRAY);
        root.addView(log);

        ScrollView sv = new ScrollView(this);
        sv.addView(root);
        setContentView(sv);
        updateShopeeModeVisibility();
        refresh();
    }

    @Override protected void onResume() { super.onResume(); refresh(); }
    @Override protected void onDestroy() {
        try { Shizuku.removeRequestPermissionResultListener(permListener); } catch (Throwable ignore) {}
        super.onDestroy();
    }

    private void updateShopeeModeVisibility() {
        shopeeModeBox.setVisibility(shopee.isChecked() ? View.VISIBLE : View.GONE);
    }

    private void saveConfig() {
        String mode = modeAll.isChecked() ? Store.MODE_ALL : Store.MODE_EXTRA;
        store.saveConfig(keyword.getText().toString(), shopee.isChecked(), lazada.isChecked(), mode);
    }

    // ---- เริ่มทำงาน ----

    private void start() {
        if (keyword.getText().toString().trim().isEmpty()) { toast("ใส่ keyword ก่อน"); return; }
        if (!shopee.isChecked() && !lazada.isChecked()) { toast("เลือก Shopee หรือ Lazada อย่างน้อยหนึ่ง"); return; }
        if (!shizukuReady()) { toast("ขอสิทธิ์ Shizuku ให้พร้อมก่อน"); requestShizuku(); return; }
        if (Build.VERSION.SDK_INT >= 23 && !Settings.canDrawOverlays(this)) {
            toast("อนุญาต 'แสดงทับแอปอื่น' ให้ ClipHarvest ก่อน (จะเปิดหน้าตั้งค่าให้)");
            startActivityForResult(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:" + getPackageName())), REQ_OVERLAY);
            return;
        }
        saveConfig();
        Intent i = new Intent(this, RunService.class);
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(i); else startService(i);
        toast("เปิดปุ่มลอยแล้ว — กด ▶ เริ่ม บนปุ่มลอยเพื่อเริ่มไล่เก็บ");
        moveTaskToBack(true);
    }

    @Override protected void onActivityResult(int req, int res, Intent data) {
        super.onActivityResult(req, res, data);
        if (req == REQ_OVERLAY) {
            if (Build.VERSION.SDK_INT >= 23 && Settings.canDrawOverlays(this)) start();
            else toast("ยังไม่ได้อนุญาตแสดงทับแอปอื่น");
        }
    }

    // ---- Shizuku ----
    private boolean shizukuReady() {
        try { return Shizuku.pingBinder() && Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED; }
        catch (Throwable t) { return false; }
    }

    private void requestShizuku() {
        try {
            if (!Shizuku.pingBinder()) { toast("เปิดแอป Shizuku แล้วสั่ง Start ก่อน"); return; }
            if (Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED) { refresh(); return; }
            if (Shizuku.shouldShowRequestPermissionRationale()) { toast("ไปเปิดสิทธิ์ให้ในแอป Shizuku"); return; }
            Shizuku.requestPermission(REQ_SHIZUKU);
        } catch (Throwable t) { toast("เรียก Shizuku ไม่ได้: " + t.getClass().getSimpleName()); }
    }

    private void refresh() {
        boolean ready = shizukuReady();
        status.setText("Shizuku: " + (ready ? "พร้อม ✓" : "ยังไม่พร้อม ✗")
                + (RunService.ALIVE ? "   ·   ปุ่มลอยเปิดอยู่" : "")
                + "\nเก็บแล้ว " + store.count() + " ลิงก์");
        status.setTextColor(ready ? Color.parseColor("#1a7f37") : Color.parseColor("#cf222e"));
        java.util.List<String> all = store.links();
        StringBuilder sb = new StringBuilder();
        for (int i = all.size() - 1; i >= 0 && sb.length() < 12000; i--)
            sb.append(all.size() - i).append(". ").append(all.get(i)).append("\n\n");
        links.setText(sb.length() == 0 ? "(ยังไม่มี)" : sb.toString());
        String lg = store.logText();
        log.setText(lg.isEmpty() ? "(ยังไม่มี log)" : tail(lg, 3000));
    }

    private static String tail(String s, int n) { return s.length() <= n ? s : s.substring(s.length() - n); }

    // ---- UI helpers ----
    private Button btn(String t, View.OnClickListener c) { Button b = new Button(this); b.setText(t); b.setAllCaps(false); b.setOnClickListener(c); return b; }
    private LinearLayout.LayoutParams eq() { return new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f); }
    private void title(LinearLayout p, String s) { TextView t = new TextView(this); t.setText(s); t.setTextSize(22); t.setTextColor(Color.BLACK); p.addView(t); }
    private void label(LinearLayout p, String s) { TextView t = new TextView(this); t.setText(s); t.setPadding(0, dp(12), 0, dp(4)); t.setTextColor(Color.DKGRAY); p.addView(t); }
    private void hint(LinearLayout p, String s) { TextView t = new TextView(this); t.setText(s); t.setTextSize(12); t.setTextColor(Color.GRAY); t.setPadding(0, dp(4), 0, dp(4)); p.addView(t); }
    private int dp(int v) { return Math.round(v * getResources().getDisplayMetrics().density); }
    private void toast(String s) { Toast.makeText(this, s, Toast.LENGTH_SHORT).show(); }
}
