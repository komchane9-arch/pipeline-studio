package th.pipeline.harvester;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.provider.Settings;
import android.text.InputType;
import android.view.View;
import android.view.ViewGroup.LayoutParams;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.FileReader;

/**
 * หน้าตั้งค่า — ใส่ keyword หลายคำ, เลือก Shopee/Lazada, ตั้งช่วงเวลาสุ่ม
 *
 * เวอร์ชันแรกเน้นปุ่ม "เปิดสิทธิ์ Accessibility" กับดูผล dump หน้าจอ
 * (ปุ่ม Dump จริงอยู่ในแถบแจ้งเตือน เพราะต้องกดตอนเปิด Shopee ค้างไว้)
 */
public class MainActivity extends Activity {

    private EditText keywords, delayMin, delayMax;
    private CheckBox shopee, lazada;
    private TextView status;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        Config cfg = new Config(this);

        // Android 13+ ต้องขอสิทธิ์แจ้งเตือน ไม่งั้นปุ่ม ‘Dump หน้าจอ’ ในแถบแจ้งเตือนจะไม่โผล่
        if (android.os.Build.VERSION.SDK_INT >= 33
                && checkSelfPermission("android.permission.POST_NOTIFICATIONS")
                   != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 1);
        }

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(16);
        root.setPadding(pad, pad, pad, pad);

        addTitle(root, "Link Harvester");
        addHint(root, "หา​ลิงก์​สินค้า​ตาม keyword แล้ว​ส่ง​เข้า​แอป pipeline links");

        addLabel(root, "Keyword (บรรทัดละคำ)");
        keywords = new EditText(this);
        keywords.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        keywords.setMinLines(3);
        keywords.setGravity(android.view.Gravity.TOP);
        keywords.setText(cfg.keywordsRaw());
        root.addView(keywords);

        shopee = new CheckBox(this);
        shopee.setText("ค้นใน Shopee (เฉพาะสินค้า EXTRA COMM)");
        shopee.setChecked(cfg.doShopee());
        root.addView(shopee);

        lazada = new CheckBox(this);
        lazada.setText("ค้นใน Lazada (เก็บทุกลิงก์ที่ค้นเจอ)");
        lazada.setChecked(cfg.doLazada());
        root.addView(lazada);

        addLabel(root, "เว้นจังหวะแบบสุ่มระหว่างการกด (วินาที)");
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        delayMin = numberField(cfg.delayMinMs() / 1000);
        delayMax = numberField(cfg.delayMaxMs() / 1000);
        row.addView(delayMin, eqWidth());
        row.addView(mkText("ถึง"), wrap());
        row.addView(delayMax, eqWidth());
        root.addView(row);

        Button save = new Button(this);
        save.setText("บันทึกการตั้งค่า");
        save.setOnClickListener(v -> saveConfig());
        root.addView(save);

        Button acc = new Button(this);
        acc.setText("เปิดสิทธิ์ Accessibility");
        acc.setOnClickListener(v ->
                startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)));
        root.addView(acc);

        Button showDump = new Button(this);
        showDump.setText("ดูผล Dump หน้าจอล่าสุด");
        showDump.setOnClickListener(v -> showDump());
        root.addView(showDump);

        addHint(root, "วิธีทดสอบ: 1) บันทึก keyword  2) เปิดสิทธิ์ Accessibility ให้ Link Harvester"
                + "  3) เปิดแอป Shopee ค้นหาสินค้า  4) ดึงแถบแจ้งเตือนลงมากด ‘Dump หน้าจอ’"
                + "  5) กลับมาแอปนี้กด ‘ดูผล Dump’ — ดูว่าเจอ EXTRA COMM กี่จุด");

        status = new TextView(this);
        status.setPadding(0, dp(12), 0, 0);
        status.setTextIsSelectable(true);
        root.addView(status);

        ScrollView scroll = new ScrollView(this);
        scroll.addView(root);
        setContentView(scroll);
    }

    private void saveConfig() {
        cfgSave();
        Toast.makeText(this, "บันทึกแล้ว", Toast.LENGTH_SHORT).show();
    }

    private void cfgSave() {
        new Config(this).save(
                keywords.getText().toString(),
                shopee.isChecked(), lazada.isChecked(),
                secToMs(delayMin), secToMs(delayMax));
    }

    private void showDump() {
        File f = new File(getExternalFilesDir(null), "dump.txt");
        if (!f.exists()) {
            status.setText("ยังไม่มีผล dump — เปิด Shopee แล้วกด ‘Dump หน้าจอ’ ในแจ้งเตือนก่อน");
            return;
        }
        StringBuilder sb = new StringBuilder();
        try (FileReader r = new FileReader(f)) {
            char[] buf = new char[4096];
            int n;
            while ((n = r.read(buf)) > 0 && sb.length() < 20000) sb.append(buf, 0, n);
        } catch (Exception e) {
            sb.append("อ่านไฟล์ไม่ได้: ").append(e.getMessage());
        }
        status.setText(sb.toString());
    }

    // ---------------------------------------------------------------- ตัวช่วย UI

    private int secToMs(EditText e) {
        try { return Integer.parseInt(e.getText().toString().trim()) * 1000; }
        catch (Exception ex) { return 5000; }
    }

    private EditText numberField(int seconds) {
        EditText e = new EditText(this);
        e.setInputType(InputType.TYPE_CLASS_NUMBER);
        e.setText(String.valueOf(seconds));
        return e;
    }

    private TextView mkText(String s) {
        TextView t = new TextView(this);
        t.setText("  " + s + "  ");
        t.setGravity(android.view.Gravity.CENTER);
        return t;
    }

    private void addTitle(LinearLayout p, String s) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(22);
        t.setTextColor(Color.BLACK);
        p.addView(t);
    }

    private void addLabel(LinearLayout p, String s) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setPadding(0, dp(14), 0, dp(4));
        t.setTextColor(Color.DKGRAY);
        p.addView(t);
    }

    private void addHint(LinearLayout p, String s) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(12);
        t.setTextColor(Color.GRAY);
        t.setPadding(0, dp(8), 0, dp(4));
        p.addView(t);
    }

    private LinearLayout.LayoutParams eqWidth() {
        return new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f);
    }

    private LinearLayout.LayoutParams wrap() {
        return new LinearLayout.LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT);
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    @Override protected void onPause() {
        super.onPause();
        cfgSave(); // เก็บอัตโนมัติ เผื่อผู้ใช้ลืมกดบันทึกก่อนสลับไปเปิด Shopee
    }
}
