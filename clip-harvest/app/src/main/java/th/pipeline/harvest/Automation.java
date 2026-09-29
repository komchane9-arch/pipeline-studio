package th.pipeline.harvest;

import android.content.Context;
import android.graphics.Bitmap;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;

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
    private static final float SHARE_ICON_X = 0.71f, SHARE_ICON_Y = 0.067f;   // ปุ่มแชร์มุมขวาบนหน้าสินค้า (ยืนยันแล้ว)
    private static final float MORE_BTN_X = 0.90f, MORE_BTN_Y = 0.83f;        // ปุ่ม "อื่นๆ" ท้ายแถวในแผงแชร์คอมมิชชั่น
    private static final int MAX_PRODUCTS = 30;         // กันวนไม่จบ (ฝั่งทดสอบตัดจบเองที่ 1 ใบ)
    private static final int MAX_SCROLLS = 12;

    private final Context ctx;
    private final Store store;
    private final ClipReader clip;
    private final Random rnd = new Random();
    private volatile boolean stopped;

    public Automation(Context ctx, ClipReader clip) {
        this.ctx = ctx;
        this.store = new Store(ctx);
        this.clip = clip;
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

        int startCount = store.count();
        int taken = 0, scrolls = 0, noProgress = 0;
        // วนเก็บจนกว่า: ครบเพดาน หรือเลื่อนแล้วไม่เจอลิงก์ใหม่ติดกันหลายรอบ (สุดผลค้นหา)
        while (go() && taken < MAX_PRODUCTS && scrolls < MAX_SCROLLS && noProgress < 3) {
            Bitmap shot = ShizukuShell.screencap();
            if (shot == null) { store.log("แคปจอไม่ได้ — หยุด"); break; }
            int w = shot.getWidth(), h = shot.getHeight();
            List<int[]> targets = mode.equals(Store.MODE_EXTRA)
                    ? extraCommProducts(shot) : allProducts(shot);
            int gained = 0;
            for (int[] xy : targets) {
                if (!go() || taken >= MAX_PRODUCTS) break;
                int before = store.count();
                openShareCollect(xy[0], xy[1], mode);
                if (store.count() > before) { taken++; gained++; }
                pause(rndDelay());
            }
            // เลื่อนลงหาสินค้าถัดไป แล้วเก็บต่อ
            ShizukuShell.swipe(w / 2, (int) (h * 0.72f), w / 2, (int) (h * 0.28f), 600);
            scrolls++;
            pause(rndDelay());
            noProgress = gained > 0 ? 0 : noProgress + 1;
        }
        store.log(pkg + " จบ · เก็บลิงก์ใหม่ " + (store.count() - startCount) + " ลิงก์ (" + scrolls + " สกรอลล์)");
    }

    // ---- ค้นหา + พิมพ์ keyword (paste รองรับไทย) ----

    private void openSearchAndType(String keyword) {
        Bitmap shot = ShizukuShell.screencap();
        int w = shot != null ? shot.getWidth() : 1080, h = shot != null ? shot.getHeight() : 2400;
        ShizukuShell.tap((int) (w * SEARCH_BAR_X), (int) (h * SEARCH_BAR_Y));   // แตะช่องค้นหา
        pause(1500);
        ShizukuShell.tap((int) (w * SEARCH_BAR_X), (int) (h * SEARCH_BAR_Y));   // โฟกัสช่องพิมพ์ให้เคอร์เซอร์ขึ้น
        pause(600);
        clearField();                                                          // ล้างคำแนะนำ/ข้อความเดิมก่อน
        if (isAscii(keyword)) {
            // HyperOS บล็อกการเขียนคลิปบอร์ดของ shell → ใช้ input text ตรงๆ (ได้เฉพาะอังกฤษ/ตัวเลข)
            ShizukuShell.typeAscii(keyword);
            store.log("พิมพ์ keyword ด้วย input text: " + keyword);
        } else {
            // ภาษาไทย input text ไม่รองรับ ลองผ่านคลิปบอร์ด (อาจโดน HyperOS บล็อก)
            boolean set = clip.setText(keyword);
            pause(400);
            ShizukuShell.key(KEY_PASTE);
            store.log("keyword ไม่ใช่อังกฤษ ลอง paste (setText=" + set + ") — ถ้าไม่เข้าต้องมี ADBKeyboard");
        }
        pause(700);
        ShizukuShell.key(KEY_ENTER);                                           // ค้นหา
        pause(300);
        store.log("กดค้นหาแล้ว");
    }

    /** ล้างข้อความในช่องค้นหา: เลื่อนไปท้ายแล้วกด DEL หลายครั้ง (กันคำแนะนำสีเทาถูกใช้แทน) */
    private void clearField() {
        ShizukuShell.key(123);           // KEYCODE_MOVE_END
        for (int i = 0; i < 40; i++) ShizukuShell.key(67);   // KEYCODE_DEL
    }

    private static boolean isAscii(String s) {
        for (int i = 0; i < s.length(); i++) if (s.charAt(i) > 127) return false;
        return true;
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

    /** เข้าสินค้า → แชร์ → (ยืนยัน EXTRA COMM) → "อื่นๆ" → ClipHarvest เก็บลิงก์ → กลับหน้าผลค้นหา */
    private void openShareCollect(int x, int y, String mode) {
        ShizukuShell.tap(x, y);                 // เข้าสินค้า
        pause(rndDelay());
        Bitmap shot = ShizukuShell.screencap();
        int w = shot != null ? shot.getWidth() : 1080, h = shot != null ? shot.getHeight() : 2400;
        ShizukuShell.tap((int) (w * SHARE_ICON_X), (int) (h * SHARE_ICON_Y));   // ปุ่มแชร์
        pause(1800);
        // ยืนยันว่าแผงแชร์คอมมิชชั่นขึ้นจริงก่อนกดต่อ (anchor "EXTRA COMM" เป็นอังกฤษ OCR อ่านได้)
        List<Ocr.Word> panel = Ocr.read(ShizukuShell.screencap());
        if (Ocr.find(panel, "COMM") == null && Ocr.find(panel, "คอมมิช") == null) {
            store.log("ไม่เจอแผงแชร์คอมมิชชั่นหลังกดแชร์ (พิกัดปุ่มแชร์อาจต้องจูน) — ถอย");
            returnToResults(mode);
            return;
        }
        // ไม่พึ่งคลิปบอร์ด (HyperOS บล็อก) — กด "อื่นๆ" ไปหน้าแชร์ระบบ แล้วเลือก ClipHarvest
        ShizukuShell.tap((int) (w * MORE_BTN_X), (int) (h * MORE_BTN_Y));       // "อื่นๆ"
        pause(1800);
        Ocr.Word ch = Ocr.find(Ocr.read(ShizukuShell.screencap()), "ClipHarvest");
        if (ch == null) {
            store.log("ไม่เจอ ClipHarvest ในหน้าแชร์ระบบ (พิกัด 'อื่นๆ' อาจต้องจูน) — ถอย");
            returnToResults(mode);
            return;
        }
        int before = store.count();
        ShizukuShell.tap(ch.cx(), ch.cy());     // ส่งลิงก์เข้า ClipHarvest → ShareInActivity เก็บเอง
        pause(1500);
        store.log(store.count() > before
                ? "เก็บลิงก์ผ่านหน้าแชร์แล้ว (รวม " + store.count() + ")"
                : "แตะ ClipHarvest แล้วแต่ยังไม่เห็นลิงก์เพิ่ม — เช็กลิงก์ที่แชร์เข้ามา");
        returnToResults(mode);
    }

    /** กด back จนกลับถึงหน้าผลค้นหา (โหมด extra ใช้ป้าย EXTRA COMM เป็นตัวยืนยันว่าถึงแล้ว) */
    private void returnToResults(String mode) {
        for (int i = 0; i < 4 && go(); i++) {
            Bitmap s = ShizukuShell.screencap();
            if (Store.MODE_EXTRA.equals(mode)) {
                List<Ocr.Word> w = Ocr.read(s);
                if (Ocr.find(w, "EXTRACOMM") != null || Ocr.find(w, "EXTRA COMM") != null) return;
            } else if (i >= 2) {
                return;   // โหมดทั้งหมดไม่มีป้ายให้จับ ถอย 2 ครั้งพอ
            }
            ShizukuShell.back();
            pause(1200);
        }
    }

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
