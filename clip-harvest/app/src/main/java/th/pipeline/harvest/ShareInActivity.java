package th.pipeline.harvest;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.widget.Toast;

/**
 * รับลิงก์แบบแชร์ตรง (ACTION_SEND) — สำรองไว้เผื่ออยากส่งเข้าเองโดยไม่พึ่ง Shizuku
 * เช่น ในหน้าแชร์ของ Shopee กด "อื่นๆ" แล้วเลือก ClipHarvest
 */
public class ShareInActivity extends Activity {
    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        String text = null;
        Intent i = getIntent();
        if (i != null && Intent.ACTION_SEND.equals(i.getAction())) {
            CharSequence cs = i.getCharSequenceExtra(Intent.EXTRA_TEXT);
            if (cs != null) text = cs.toString().trim();
        }
        if (text != null && !text.isEmpty()) {
            Store store = new Store(this);
            boolean fresh = store.matches(text) && store.add(text);
            if (fresh) {
                String forward = store.forwardUrl();
                if (!forward.isEmpty()) {
                    final String t = text;
                    new Thread(() -> Forwarder.post(forward, t)).start();
                }
            }
            Toast.makeText(this, fresh ? "เก็บลิงก์แล้ว · รวม " + store.count()
                    : "ลิงก์นี้ไม่เข้าเงื่อนไข หรือมีอยู่แล้ว", Toast.LENGTH_SHORT).show();
        }
        finish();
    }
}
