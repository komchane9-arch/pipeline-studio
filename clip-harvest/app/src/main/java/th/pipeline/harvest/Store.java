package th.pipeline.harvest;

import android.content.Context;
import android.content.SharedPreferences;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/** ค่าตั้งค่า + รายการลิงก์ที่ดักได้ — เก็บใน SharedPreferences ให้ทั้ง Activity และ Service ใช้ร่วมกัน */
public class Store {
    private static final String FILE = "clipharvest";
    // ค่าเริ่มต้นแบบเดียวกับ clippipe
    public static final String DEFAULT_KEYWORDS = "shopee.co.th,s.shopee,lazada.co.th,s.lazada";
    private final SharedPreferences sp;

    public Store(Context ctx) {
        sp = ctx.getApplicationContext().getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    // ---- ตั้งค่า ----
    public String keywordsRaw() { return sp.getString("keywords", DEFAULT_KEYWORDS); }
    public String forwardUrl() { return sp.getString("forwardUrl", "").trim(); }
    public int pollMs() { return sp.getInt("pollMs", 900); }
    public boolean running() { return sp.getBoolean("running", false); }

    public void setRunning(boolean v) { sp.edit().putBoolean("running", v).apply(); }

    public void saveConfig(String keywords, String forwardUrl, int pollMs) {
        sp.edit()
          .putString("keywords", keywords.trim())
          .putString("forwardUrl", forwardUrl.trim())
          .putInt("pollMs", Math.max(400, pollMs))
          .apply();
    }

    /** คำที่ต้องมีในข้อความถึงจะเก็บ (ว่าง = เก็บทุกอย่าง) */
    public List<String> keywords() {
        List<String> out = new ArrayList<>();
        for (String k : keywordsRaw().split(",")) {
            String t = k.trim().toLowerCase();
            if (!t.isEmpty()) out.add(t);
        }
        return out;
    }

    public boolean matches(String text) {
        List<String> ks = keywords();
        if (ks.isEmpty()) return true;
        String low = text.toLowerCase();
        for (String k : ks) if (low.contains(k)) return true;
        return false;
    }

    // ---- ลิงก์ที่ดักได้ (ไม่ซ้ำ เรียงตามเวลาที่เจอ) ----
    private Set<String> load() {
        // LinkedHashSet ผ่าน getStringSet ไม่รักษาลำดับ จึงเก็บเป็นสตริงคั่นบรรทัดเอง
        String blob = sp.getString("links", "");
        Set<String> set = new LinkedHashSet<>();
        if (!blob.isEmpty()) for (String s : blob.split("\n")) if (!s.isEmpty()) set.add(s);
        return set;
    }

    /** เพิ่มลิงก์ คืน true ถ้าเป็นของใหม่ (ยังไม่เคยเก็บ) */
    public synchronized boolean add(String link) {
        Set<String> set = load();
        if (!set.add(link)) return false;
        StringBuilder sb = new StringBuilder();
        for (String s : set) sb.append(s).append('\n');
        sp.edit().putString("links", sb.toString()).apply();
        return true;
    }

    public List<String> links() { return new ArrayList<>(load()); }
    public int count() { return load().size(); }
    public void clear() { sp.edit().remove("links").apply(); }

    /** ลิงก์ล่าสุดที่เห็นในคลิปบอร์ด — กันเก็บซ้ำรัวๆ จากการ poll เดิมค่าเดิม */
    public String lastSeen() { return sp.getString("lastSeen", ""); }
    public void setLastSeen(String v) { sp.edit().putString("lastSeen", v).apply(); }
}
