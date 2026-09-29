package th.pipeline.harvester;

import android.content.Context;
import android.content.SharedPreferences;

import java.util.ArrayList;
import java.util.List;

/** ค่าที่ผู้ใช้ตั้งไว้ — เก็บใน SharedPreferences ให้ทั้ง Activity และ Service อ่านร่วมกัน */
public class Config {
    private static final String FILE = "harvester";
    public static final String TARGET_PACKAGE = "th.pipeline.links"; // แอปปลายทางที่รับลิงก์
    public static final String SHOPEE = "com.shopee.th";
    public static final String LAZADA = "com.lazada.android";

    private final SharedPreferences sp;

    public Config(Context ctx) {
        sp = ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    /** keyword ทีละบรรทัด ตัดบรรทัดว่างทิ้ง */
    public List<String> keywords() {
        List<String> out = new ArrayList<>();
        for (String line : sp.getString("keywords", "").split("\\n")) {
            String k = line.trim();
            if (!k.isEmpty()) out.add(k);
        }
        return out;
    }

    public String keywordsRaw() { return sp.getString("keywords", ""); }
    public boolean doShopee() { return sp.getBoolean("shopee", true); }
    public boolean doLazada() { return sp.getBoolean("lazada", false); }
    public int delayMinMs() { return sp.getInt("delayMin", 4000); }
    public int delayMaxMs() { return sp.getInt("delayMax", 9000); }

    public void save(String keywords, boolean shopee, boolean lazada, int delayMinMs, int delayMaxMs) {
        sp.edit()
          .putString("keywords", keywords)
          .putBoolean("shopee", shopee)
          .putBoolean("lazada", lazada)
          .putInt("delayMin", Math.max(1500, delayMinMs))
          .putInt("delayMax", Math.max(Math.max(1500, delayMinMs), delayMaxMs))
          .apply();
    }
}
