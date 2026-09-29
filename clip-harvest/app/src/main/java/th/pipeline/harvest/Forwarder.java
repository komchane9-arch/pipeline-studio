package th.pipeline.harvest;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** ส่งลิงก์ที่ดักได้ไปที่ URL ที่ตั้งไว้ (POST ข้อความดิบ) — เว้นว่างก็ไม่ส่ง เก็บในเครื่องอย่างเดียว */
public class Forwarder {

    /** ยิงในเธรดพื้นหลังเสมอ — เรียกจาก service ที่ไม่ใช่ main thread */
    public static void post(String url, String link) {
        if (url == null || url.isEmpty()) return;
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(url).openConnection();
            conn.setConnectTimeout(8000);
            conn.setReadTimeout(8000);
            conn.setRequestMethod("POST");
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "text/plain; charset=utf-8");
            byte[] body = link.getBytes(StandardCharsets.UTF_8);
            try (OutputStream os = conn.getOutputStream()) {
                os.write(body);
            }
            conn.getResponseCode(); // ต้องเรียกให้ request ถูกส่งจริง
        } catch (Exception ignore) {
            // ส่งไม่สำเร็จก็ไม่เป็นไร ลิงก์ยังถูกเก็บในเครื่องแล้ว
        } finally {
            if (conn != null) conn.disconnect();
        }
    }
}
