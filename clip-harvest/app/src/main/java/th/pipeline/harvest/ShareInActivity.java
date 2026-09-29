package th.pipeline.harvest;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.widget.Toast;

/**
 * รับลิงก์แบบแชร์ตรง (ACTION_SEND) — สำรองไว้เผื่ออยากส่งลิงก์เข้าเอง
 * เช่นในหน้าแชร์ของ Shopee กด "อื่นๆ" แล้วเลือก ClipHarvest
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
            boolean fresh = store.add(text);
            Toast.makeText(this, fresh ? "เก็บลิงก์แล้ว · รวม " + store.count() : "ลิงก์นี้มีอยู่แล้ว",
                    Toast.LENGTH_SHORT).show();
        }
        finish();
    }
}
