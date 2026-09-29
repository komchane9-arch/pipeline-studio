package th.pipeline.harvest;

import android.content.Context;
import android.content.SharedPreferences;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/** ค่าตั้งค่า + รายการลิงก์ที่เก็บได้ + log — ใช้ร่วมกันทั้ง Activity และ Service */
public class Store {
    private static final String FILE = "clipharvest";
    public static final String MODE_EXTRA = "extra";   // เอาแค่ EXTRA COMM
    public static final String MODE_ALL = "all";       // เอาทุกสินค้า

    private final SharedPreferences sp;

    public Store(Context ctx) {
        sp = ctx.getApplicationContext().getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    // ---- ตั้งค่าที่ผู้ใช้กรอก ----
    public String keyword() { return sp.getString("keyword", "").trim(); }
    public boolean doShopee() { return sp.getBoolean("shopee", true); }
    public boolean doLazada() { return sp.getBoolean("lazada", false); }
    /** โหมดของ Shopee: extra = เอาแค่ EXTRA COMM, all = เอาทั้งหมด */
    public String shopeeMode() { return sp.getString("shopeeMode", MODE_EXTRA); }
    /** เว้นกี่วินาทีก่อนสลับจาก Shopee ไป Lazada */
    public int gapBetweenPlatformsSec() { return sp.getInt("gapPlatform", 90); }

    public void saveConfig(String keyword, boolean shopee, boolean lazada, String shopeeMode) {
        sp.edit()
          .putString("keyword", keyword.trim())
          .putBoolean("shopee", shopee)
          .putBoolean("lazada", lazada)
          .putString("shopeeMode", MODE_ALL.equals(shopeeMode) ? MODE_ALL : MODE_EXTRA)
          .apply();
    }

    public boolean running() { return sp.getBoolean("running", false); }
    public void setRunning(boolean v) { sp.edit().putBoolean("running", v).apply(); }

    // ---- ลิงก์ที่เก็บได้ (ไม่ซ้ำ เรียงตามเวลาที่เจอ) ----
    private Set<String> load() {
        String blob = sp.getString("links", "");
        Set<String> set = new LinkedHashSet<>();
        if (!blob.isEmpty()) for (String s : blob.split("\n")) if (!s.isEmpty()) set.add(s);
        return set;
    }

    public synchronized boolean add(String link) {
        link = link.trim();
        if (link.isEmpty()) return false;
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

    // ---- log ให้ผู้ใช้/ตัวจูนดูว่าโปรแกรมทำอะไรไปบ้าง ----
    public synchronized void log(String line) {
        String prev = sp.getString("log", "");
        String stamped = time() + " " + line + "\n";
        String all = prev + stamped;
        if (all.length() > 20000) all = all.substring(all.length() - 20000);
        sp.edit().putString("log", all).apply();
    }

    public String logText() { return sp.getString("log", ""); }
    public void clearLog() { sp.edit().remove("log").apply(); }

    private static String time() {
        return new java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.US)
                .format(new java.util.Date());
    }
}
