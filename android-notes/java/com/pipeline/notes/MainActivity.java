package com.pipeline.notes;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.net.HttpURLConnection;
import java.net.URL;

/**
 * แอปโน้ต — หน้าต่างบางๆ ที่เปิดสมุดโน้ตซึ่งอยู่บนคอมของเจ้าของ
 *
 * เจ้าของสั่ง 21 ก.ย. 2569 — "ติดตั้งเป็น apk ในเครื่องผมเลย"
 *
 * **แอปนี้ไม่เก็บโน้ตเองสักตัว** ข้อมูลอยู่ที่คอมที่เดียว จึงไม่มีการซิงก์ให้ต้อง
 * มาแก้ชนกัน พิมพ์บนคอมแล้วเปิดแอปก็เห็น พิมพ์ในแอปแล้วดูบนคอมก็เห็น
 *
 * **ลองที่อยู่หลายทางแล้วเลือกอันที่ตอบ ไม่ฝังทางเดียวตายตัว**
 * วัดจริง 21 ก.ย. 2569 บน Xiaomi 11T pro: เครื่องนี้ไม่มีแอป Tailscale
 * ที่อยู่ Tailscale จึงใช้ไม่ได้ (ERR_NAME_NOT_RESOLVED) แต่อยู่ WiFi บ้าน
 * เดียวกันและเรียก laptop-ipb0ansq.local ได้ — ถ้าฝังทางเดียวก็จบตั้งแต่แรก
 *
 * เรียงจากทางที่ใช้ได้กว้างสุดไปแคบสุด
 *   1. Tailscale   ใช้ได้ทุกที่ ไม่ต้องอยู่บ้าน (ต้องลงแอป Tailscale ก่อน)
 *   2. ชื่อเครื่องในวง WiFi   ใช้ได้เฉพาะที่บ้าน แต่ IP เปลี่ยนก็ยังใช้ได้
 *   3. เลข IP ตรงๆ   ทางสุดท้าย เผื่อ mDNS ในเราเตอร์ปิดอยู่
 */
public class MainActivity extends Activity {

    private static final String[] CANDIDATES = {
        "https://laptop-ipb0ansq.tailcb70ec.ts.net",
        "http://laptop-ipb0ansq.local:8866",
        "http://192.168.1.101:8866",
    };

    /** ที่อยู่ที่ใช้ตรวจ — **ต้องเป็นของที่ได้เฉพาะตอนใช้งานได้จริงเท่านั้น**
     *
     *  วัดจริง 21 ก.ย. 2569: ตอนแรกใช้ /api/access/status ซึ่งเซิร์ฟเวอร์เปิดให้
     *  ทุกเครื่องเรียกได้แม้ยังไม่ได้รับอนุญาต — ตอบ 200 เหมือนกันหมด ตัวตรวจ
     *  เลยบอกว่า "ต่อได้" แล้วแอปไปเปิดเจอหน้า "รอเครื่องหลักอนุญาต" แทนโน้ต
     *
     *  /api/notes ให้ 200 เฉพาะเครื่องที่มีสิทธิ์จริง ที่เหลือได้ 403 */
    private static final String PROBE = "/api/notes";

    private static final int PROBE_MS = 2500;
    private static final String PREFS = "notes-app";
    private static final String KEY_BASE = "base";

    private WebView web;
    private LinearLayout trouble;
    private TextView troubleText;
    private EditText addressBox;
    private boolean lastLoadFailed = false;

    @Override
    @SuppressLint("SetJavaScriptEnabled")
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setFitsSystemWindows(true);

        web = new WebView(this);
        web.setLayoutParams(new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        WebSettings set = web.getSettings();
        set.setJavaScriptEnabled(true);
        set.setDomStorageEnabled(true);
        set.setDatabaseEnabled(true);
        set.setUseWideViewPort(true);
        set.setLoadWithOverviewMode(false);
        set.setSupportZoom(false);
        set.setBuiltInZoomControls(false);
        set.setTextZoom(100);
        set.setCacheMode(WebSettings.LOAD_DEFAULT);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            set.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        }
        // เปิดไว้เพื่อให้ไล่ปัญหาจากคอมได้ผ่าน chrome://inspect
        // (แอปใช้ในวงส่วนตัว ไม่ได้ปล่อยขึ้นสโตร์)
        WebView.setWebContentsDebuggingEnabled(true);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return false;   // ลิงก์ร้านค้าในโน้ตเปิดในแอปนี้เลย
            }

            @Override
            public void onPageStarted(WebView view, String url, android.graphics.Bitmap icon) {
                lastLoadFailed = false;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (!lastLoadFailed) showWeb();
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request,
                                        WebResourceError error) {
                if (request != null && !request.isForMainFrame()) return;
                lastLoadFailed = true;
                String why = "";
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && error != null) {
                    why = String.valueOf(error.getDescription());
                }
                showTrouble(why);
            }
        });

        trouble = buildTrouble();
        root.addView(web);
        root.addView(trouble);
        setContentView(root);

        connect();
    }

    /** หาที่อยู่ที่ตอบจริง แล้วค่อยเปิด — ทำในเธรดแยกเพราะยิงเน็ตบนเธรดหลักไม่ได้ */
    private void connect() {
        final String saved = prefs().getString(KEY_BASE, null);
        new Thread(() -> {
            String found = null;
            boolean sawLocked = false;
            if (saved != null) {
                int code = answers(saved);
                if (code == 200) found = saved;
                else if (code == 403) sawLocked = true;
            }
            if (found == null) {
                for (String base : CANDIDATES) {
                    int code = answers(base);
                    if (code == 200) { found = base; break; }
                    if (code == 403) sawLocked = true;
                }
            }
            final String base = found;
            final boolean locked = sawLocked;
            runOnUiThread(() -> {
                if (base == null) {
                    showTrouble(locked
                        ? "ต่อถึงคอมได้แล้ว แต่เครื่องนี้ยังไม่ได้รับอนุญาต — "
                          + "เปิด Pipeline Studio บนคอม → ตั้งค่า → อุปกรณ์ที่ขอเข้าใช้ "
                          + "→ กดอนุญาต แล้วกดลองใหม่"
                        : "ลองครบทุกที่อยู่แล้วไม่มีที่ไหนตอบ");
                    return;
                }
                prefs().edit().putString(KEY_BASE, base).apply();
                lastLoadFailed = false;
                showWeb();
                web.loadUrl(base + "/notes");
            });
        }).start();
    }

    /** เซิร์ฟเวอร์ตอบไหม — คืนรหัสที่ได้จริง (0 = ต่อไม่ติดเลย)
     *
     *  **แยก "ต่อไม่ติด" ออกจาก "ต่อติดแต่ยังไม่มีสิทธิ์"** สองอย่างนี้แก้คนละทาง
     *  อย่างแรกคือเน็ต/ที่อยู่ผิด อย่างหลังคือต้องไปกดอนุญาตที่คอม */
    private int answers(String base) {
        HttpURLConnection link = null;
        try {
            link = (HttpURLConnection) new URL(base + PROBE).openConnection();
            link.setConnectTimeout(PROBE_MS);
            link.setReadTimeout(PROBE_MS);
            link.setRequestMethod("GET");
            link.setInstanceFollowRedirects(false);
            return link.getResponseCode();
        } catch (Exception ignored) {
            return 0;
        } finally {
            if (link != null) link.disconnect();
        }
    }

    private LinearLayout buildTrouble() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(56, 56, 56, 56);
        box.setVisibility(View.GONE);
        box.setLayoutParams(new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        TextView head = new TextView(this);
        head.setText("เปิดสมุดโน้ตไม่ได้");
        head.setTextSize(20);
        head.setPadding(0, 0, 0, 24);

        troubleText = new TextView(this);
        troubleText.setTextSize(14);
        troubleText.setLineSpacing(9f, 1f);
        troubleText.setPadding(0, 0, 0, 28);

        TextView label = new TextView(this);
        label.setText("ที่อยู่ของสมุดโน้ต (แก้เองได้)");
        label.setTextSize(13);
        label.setPadding(0, 0, 0, 8);

        addressBox = new EditText(this);
        addressBox.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        addressBox.setSingleLine(true);
        addressBox.setTextSize(13);

        Button again = new Button(this);
        again.setText("ลองใหม่");
        again.setOnClickListener(v -> {
            String typed = addressBox.getText().toString().trim();
            SharedPreferences.Editor edit = prefs().edit();
            if (typed.isEmpty()) {
                edit.remove(KEY_BASE);
            } else {
                if (!typed.startsWith("http://") && !typed.startsWith("https://")) {
                    typed = "http://" + typed;
                }
                while (typed.endsWith("/")) typed = typed.substring(0, typed.length() - 1);
                if (typed.endsWith("/notes")) {
                    typed = typed.substring(0, typed.length() - "/notes".length());
                }
                edit.putString(KEY_BASE, typed);
            }
            edit.apply();
            troubleText.setText("กำลังลองใหม่…");
            connect();
        });

        box.addView(head);
        box.addView(troubleText);
        box.addView(label);
        box.addView(addressBox);
        box.addView(again);
        return box;
    }

    private void showTrouble(String why) {
        StringBuilder words = new StringBuilder();
        words.append("โน้ตทั้งหมดเก็บอยู่ที่คอม แอปนี้เป็นแค่หน้าต่างที่เปิดไปดู\n\n")
             .append("เช็คตามนี้\n")
             .append("1. คอมเปิดอยู่ไหม และเปิดโปรแกรม Pipeline Studio ค้างไว้หรือเปล่า\n")
             .append("2. ถ้าไม่ได้อยู่บ้าน ต้องลงแอป Tailscale ในมือถือเครื่องนี้ก่อน\n")
             .append("3. ถ้าอยู่บ้าน เช็คว่าต่อ WiFi วงเดียวกับคอมอยู่\n\n")
             .append("ที่อยู่ที่ลองไปแล้ว\n");
        for (String base : CANDIDATES) {
            words.append("  • ").append(base).append("\n");
        }
        if (why != null && !why.isEmpty()) {
            words.append("\nเครื่องแจ้งว่า: ").append(why);
        }
        troubleText.setText(words.toString());
        String saved = prefs().getString(KEY_BASE, "");
        addressBox.setText(saved);
        web.setVisibility(View.GONE);
        trouble.setVisibility(View.VISIBLE);
    }

    private void showWeb() {
        trouble.setVisibility(View.GONE);
        web.setVisibility(View.VISIBLE);
    }

    private SharedPreferences prefs() {
        return getSharedPreferences(PREFS, MODE_PRIVATE);
    }

    @Override
    protected void onResume() {
        super.onResume();
        // บอกหน้าเว็บว่ากลับมาเห็นแล้ว — ตัวหน้าเว็บจะดึงโน้ตใหม่เอง
        // (ไม่สั่ง reload เองเพราะจะทิ้งข้อความที่ยังพิมพ์ค้างอยู่)
        web.onResume();
        web.resumeTimers();
    }

    @Override
    protected void onPause() {
        // หน้าเว็บบันทึกข้อความที่ค้างอยู่ตอนถูกซ่อน จึงต้องบอกมันก่อนหยุด
        web.onPause();
        super.onPause();
    }

    @Override
    public boolean onKeyDown(int code, KeyEvent event) {
        if (code == KeyEvent.KEYCODE_BACK && web.getVisibility() == View.VISIBLE
                && web.canGoBack()) {
            web.goBack();
            return true;
        }
        return super.onKeyDown(code, event);
    }
}
