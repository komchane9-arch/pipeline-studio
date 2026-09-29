package th.pipeline.harvest;

import android.content.Context;
import android.graphics.Bitmap;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Random;
import java.util.Set;

/**
 * กลไกขับ Shopee/Lazada: ค้นหาตาม keyword → เข้าสินค้า → แชร์ → คัดลอกลิงก์ → เก็บลิงก์
 *
 * **พิกัดในไฟล์นี้เป็นค่าเริ่มต้นที่ต้องจูนกับหน้าจอจริง** (เก็บเป็นสัดส่วนของจอเพื่อไม่ผูกกับ
 * ความละเอียดตายตัว) จุดที่เป็นไอคอน (ปุ่มแชร์) ไม่มีข้อความให้ OCR จับ จึงใช้พิกัดสัดส่วน
 * ส่วนที่เป็นข้อความอังกฤษ (EXTRA COMM) ใช้ OCR หาได้จริง
 */
public class Automation {

    public static final String SHOPEE = "com.shopee.th";
    public static final String LAZADA = "com.lazada.android";
    private static final int KEY_PASTE = 279, KEY_ENTER = 66;

    // ---- พิกัดสัดส่วน (0..1) ที่ต้องจูน ----
    private static final float SEARCH_BAR_X = 0.40f, SEARCH_BAR_Y = 0.067f;   // ช่องค้นหาบนสุด
    private static final float SHARE_ICON_X = 0.71f, SHARE_ICON_Y = 0.067f;   // ปุ่มแชร์มุมขวาบนหน้าสินค้า
    private static final float COPY_LINK_X = 0.34f, COPY_LINK_Y = 0.83f;      // ปุ่ม "คัดลอกลิงก์" ในแผงแชร์คอมมิชชั่น
    private static final int MAX_PRODUCTS = 30;         // กันวนไม่จบ
    private static final int MAX_SCROLLS = 12;

    private final Context ctx;
    private final Store store;
    private final ClipReader clip;
    private final Runnable stopCheck;   // คืน true ผ่าน isStopped()
    private final Random rnd = new Random();
    private volatile boolean stopped;

    public Automation(Context ctx, ClipReader clip) {
        this.ctx = ctx;
        this.store = new Store(ctx);
        this.clip = clip;
        this.stopCheck = null;
    }

    public void stop() { stopped = true; }
    private boolean go() { return !stopped; }

    // ---- ลำดับงานหลัก ----

    public void run() {
        String kw = store.keyword();
        if (kw.isEmpty()) { store.log("ยังไม่ได้ใส่ keyword — หยุด"); return; }

        if (store.doShopee() && go()) {
            store.log("== Shopee: ค้นหา \"" + kw + "\" (โหมด " + store.shopeeMode() + ") ==");
            try { doPlatform(SHOPEE, kw, store.shopeeMode()); }
            catch (Throwable t) { store.log("Shopee ล้ม: " + t); }
        }

        if (store.doShopee() && store.doLazada() && go()) {
            int sec = store.gapBetweenPlatformsSec();
            store.log("เว้น " + sec + " วินาทีก่อนทำ Lazada");
            sleep(sec * 1000L);
        }

        if (store.doLazada() && go()) {
            store.log("== Lazada: ค้นหา \"" + kw + "\" (เก็บทุกลิงก์) ==");
            try { doPlatform(LAZADA, kw, Store.MODE_ALL); }
            catch (Throwable t) { store.log("Lazada ล้ม: " + t); }
        }
        store.log("จบงาน · เก็บได้รวม " + store.count() + " ลิงก์");
    }

    // ---- ต่อแพลตฟอร์ม ----

    private void doPlatform(String pkg, String keyword, String mode) {
        ShizukuShell.forceStop(pkg);
        pause(1500);
        ShizukuShell.launch(pkg);
        pause(6000);                       // รอแอปเปิด
        if (!go()) return;

        openSearchAndType(keyword);
        pause(4000);                       // รอผลค้นหา
        if (!go()) return;

        Set<String> visited = new HashSet<>();
        int taken = 0, scrolls = 0;
        while (go() && taken < MAX_PRODUCTS && scrolls < MAX_SCROLLS) {
            Bitmap shot = ShizukuShell.screencap();
            if (shot == null) { store.log("แคปจอไม่ได้ — หยุด"); break; }
            List<int[]> targets = mode.equals(Store.MODE_EXTRA)
                    ? extraCommProducts(shot) : allProducts(shot);
            int before = taken;
            for (int[] xy : targets) {
                if (!go() || taken >= MAX_PRODUCTS) break;
                String key = xy[0] + "," + (xy[1] / 100);   // กันกดซ้ำการ์ดเดิม
                if (!visited.add(key)) continue;
                if (openShareCopy(xy[0], xy[1])) taken++;
            }
            // เลื่อนลงหาสินค้าถัดไป
            int w = shot.getWidth(), h = shot.getHeight();
            ShizukuShell.swipe(w / 2, (int) (h * 0.75f), w / 2, (int) (h * 0.30f), 600);
            scrolls++;
            pause(rndDelay());
            if (taken == before) {
                // ไม่เจอสินค้าใหม่ในรอบนี้ ลองเลื่อนอีกครั้งก่อนยอมแพ้
                if (scrolls >= 3 && targets.isEmpty()) { store.log("ไม่เจอสินค้าเพิ่ม — หยุดแพลตฟอร์มนี้"); break; }
            }
        }
        store.log(pkg + " เก็บได้ " + taken + " สินค้าในรอบนี้");
    }

    // ---- ค้นหา + พิมพ์ keyword (paste รองรับไทย) ----

    private void openSearchAndType(String keyword) {
        Bitmap shot = ShizukuShell.screencap();
        int w = shot != null ? shot.getWidth() : 1080, h = shot != null ? shot.getHeight() : 2400;
        ShizukuShell.tap((int) (w * SEARCH_BAR_X), (int) (h * SEARCH_BAR_Y));   // แตะช่องค้นหา
        pause(1500);
        clip.setText(keyword);                                                 // ตั้งคลิปบอร์ด = keyword
        pause(400);
        ShizukuShell.tap((int) (w * SEARCH_BAR_X), (int) (h * SEARCH_BAR_Y));   // โฟกัสช่องพิมพ์
        pause(400);
        ShizukuShell.key(KEY_PASTE);                                           // paste
        pause(600);
        ShizukuShell.key(KEY_ENTER);                                           // ค้นหา
        store.log("พิมพ์ keyword และค้นหาแล้ว");
    }

    // ---- หาสินค้า ----

    /** ตำแหน่งสินค้า EXTRA COMM: หาข้อความ EXTRA COMM แล้วเล็งไปที่รูปสินค้าเหนือป้าย */
    private List<int[]> extraCommProducts(Bitmap shot) {
        List<int[]> out = new ArrayList<>();
        List<Ocr.Word> words = Ocr.read(shot);
        List<Ocr.Word> badges = Ocr.findAll(words, "EXTRACOMM");
        badges.addAll(Ocr.findAll(words, "EXTRA COMM"));
        int cardUp = (int) (shot.getHeight() * 0.13f);   // รูปสินค้าอยู่เหนือป้ายประมาณเท่านี้
        for (Ocr.Word b : badges) out.add(new int[]{b.cx(), Math.max(1, b.cy() - cardUp)});
        store.log("รอบนี้เจอ EXTRA COMM " + out.size() + " จุด (อ่านข้อความได้ " + words.size() + " คำ)");
        return out;
    }

    /** ตำแหน่งสินค้าทุกตัว: เล็งกลางรูปสินค้าตามกริด 2 คอลัมน์ (ค่าเริ่มต้น ต้องจูน) */
    private List<int[]> allProducts(Bitmap shot) {
        List<int[]> out = new ArrayList<>();
        int w = shot.getWidth(), h = shot.getHeight();
        float[] cols = {0.26f, 0.74f};
        float[] rows = {0.30f, 0.66f};       // สองแถวที่เห็นในจอเดียว
        for (float ry : rows) for (float cx : cols) out.add(new int[]{(int) (w * cx), (int) (h * ry)});
        return out;
    }

    // ---- เข้าสินค้า → แชร์ → คัดลอกลิงก์ → เก็บ ----

    private boolean openShareCopy(int x, int y) {
        String before = clip.read(ctx);
        ShizukuShell.tap(x, y);                 // เข้าสินค้า
        pause(rndDelay());
        Bitmap shot = ShizukuShell.screencap();
        int w = shot != null ? shot.getWidth() : 1080, h = shot != null ? shot.getHeight() : 2400;
        ShizukuShell.tap((int) (w * SHARE_ICON_X), (int) (h * SHARE_ICON_Y));   // ปุ่มแชร์
        pause(1800);
        ShizukuShell.tap((int) (w * COPY_LINK_X), (int) (h * COPY_LINK_Y));     // คัดลอกลิงก์
        pause(1200);
        String link = clip.read(ctx).trim();
        boolean ok = false;
        if (!link.isEmpty() && !link.equals(before) && looksLikeLink(link)) {
            if (store.add(link)) { store.log("เก็บลิงก์: " + trim(link)); ok = true; }
            else store.log("ลิงก์ซ้ำ ข้าม: " + trim(link));
        } else {
            store.log("ไม่ได้ลิงก์ (คลิปบอร์ด=" + trim(link) + ") — พิกัดแชร์/คัดลอกอาจต้องจูน");
        }
        ShizukuShell.back();    // ปิดแผงแชร์
        pause(500);
        ShizukuShell.back();    // ออกจากหน้าสินค้า
        pause(rndDelay());
        return ok;
    }

    private static boolean looksLikeLink(String s) {
        String l = s.toLowerCase();
        return l.contains("shopee.co") || l.contains("s.shopee") || l.contains("lazada")
                || l.contains("http");
    }

    private static String trim(String s) { return s.length() > 60 ? s.substring(0, 60) + "…" : s; }

    // ---- เว้นจังหวะแบบสุ่ม (เลียนแบบคน) ----
    private long rndDelay() { return 2500 + rnd.nextInt(3000); }   // 2.5–5.5 วิ
    private void pause(long ms) { sleep(ms); }
    private void sleep(long ms) {
        long end = System.currentTimeMillis() + ms;
        while (go() && System.currentTimeMillis() < end) {
            try { Thread.sleep(200); } catch (InterruptedException e) { return; }
        }
    }
}
