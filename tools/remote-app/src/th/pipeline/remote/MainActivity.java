package th.pipeline.remote;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Bundle;
import android.view.KeyEvent;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/**
 * Pipeline Remote — แอปพลิเคชันรีโมทหน้าจอมือถือสำหรับ Xiaomi 11T Pro
 * รองรับ WebCodecs, WebSocket, ระบบสลับอัตโนมัติระหว่าง USB (127.0.0.1) และ Wi-Fi LAN
 */
public class MainActivity extends Activity {

    private static final int FILE_CHOOSER_REQUEST_CODE = 1001;
    private static final String PREF_NAME = "remote_app_prefs";
    private static final String KEY_SERVER_URL = "server_url";

    private WebView web;
    private ValueCallback<Uri[]> filePathCallback;

    public class AppInterface {
        @JavascriptInterface
        public void setServerUrl(String url) {
            if (url == null || url.trim().isEmpty()) return;
            String clean = url.trim();
            if (!clean.startsWith("http://") && !clean.startsWith("https://")) {
                clean = "http://" + clean;
            }
            if (!clean.contains("/remote") && !clean.contains("/static/remote.html")) {
                clean = clean.replaceAll("/+$", "") + "/static/remote.html";
            }
            final String target = clean;
            getSharedPreferences(PREF_NAME, MODE_PRIVATE)
                    .edit()
                    .putString(KEY_SERVER_URL, target)
                    .apply();

            runOnUiThread(() -> web.loadUrl(target));
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        WebView.setWebContentsDebuggingEnabled(true);

        web = new WebView(this);
        setContentView(web);

        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setSupportZoom(false);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);

        web.addJavascriptInterface(new AppInterface(), "AppHost");

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                String host = uri.getHost();
                if ("127.0.0.1".equals(host) || "localhost".equals(host) 
                        || (host != null && (host.startsWith("192.168.") || host.endsWith(".ts.net") || host.contains("tailcb70ec")))) {
                    return false;
                }
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, uri));
                } catch (Exception ignored) {}
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                if (url != null && (url.contains("/remote") || url.contains("/static/remote.html"))) {
                    getSharedPreferences(PREF_NAME, MODE_PRIVATE)
                            .edit()
                            .putString(KEY_SERVER_URL, url)
                            .apply();
                }
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (!request.isForMainFrame()) return;

                String currentUrl = getCurrentServerUrl();
                String usbUrl = getString(R.string.start_url);
                String lanUrl = getString(R.string.lan_url);
                String tailUrl = getString(R.string.tailscale_url);

                String errorHtml = "<!doctype html><html lang=\"th\"><head>"
                        + "<meta charset=\"utf-8\">"
                        + "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                        + "<style>"
                        + "body{background:#090d13;color:#f0f6fc;font-family:-apple-system,BlinkMacSystemFont,sans-serif;"
                        + "display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:16px;box-sizing:border-box;text-align:center;}"
                        + ".card{padding:24px;background:#161b22;border:1px solid #30363d;border-radius:14px;max-width:340px;width:100%;box-shadow:0 8px 24px rgba(0,0,0,0.5);}"
                        + "h2{font-size:18px;margin:12px 0 6px;color:#f0f6fc;}p{color:#8b949e;font-size:13px;line-height:1.5;margin:6px 0 16px;}"
                        + ".btn{width:100%;background:#238636;color:#fff;border:none;padding:12px;border-radius:8px;font-weight:600;font-size:14px;margin-bottom:8px;cursor:pointer;display:block;}"
                        + ".btn-tail{background:#1f6feb;color:#fff;border:none;}"
                        + ".btn-sec{background:#21262d;border:1px solid #30363d;color:#c9d1d9;}"
                        + ".btn:active{opacity:0.8;}"
                        + "input{width:100%;box-sizing:border-box;background:#0d1117;border:1px solid #30363d;color:#f0f6fc;padding:10px;border-radius:8px;font-size:13px;margin-bottom:8px;text-align:center;}"
                        + ".small-note{font-size:11px;color:#6e7681;margin-top:12px;}"
                        + "</style></head><body><div class=\"card\">"
                        + "<div style=\"font-size:42px;\">📱⌁🖥️</div>"
                        + "<h2>กำลังเชื่อมต่อคอมพิวเตอร์…</h2>"
                        + "<p>เลือกช่องทางเชื่อมต่อตามการใช้งานของคุณ</p>"
                        + "<button class=\"btn\" onclick=\"AppHost.setServerUrl('" + usbUrl + "')\">🔌 เชื่อมต่อผ่าน USB (127.0.0.1)</button>"
                        + "<button class=\"btn btn-tail\" onclick=\"AppHost.setServerUrl('" + tailUrl + "')\">🌐 เชื่อมต่อผ่าน 5G (Tailscale)</button>"
                        + "<button class=\"btn btn-sec\" onclick=\"AppHost.setServerUrl('" + lanUrl + "')\">📶 เชื่อมต่อผ่าน Wi-Fi (วงเดียวกัน)</button>"
                        + "<div style=\"margin-top:16px; border-top:1px solid #30363d; padding-top:14px;\">"
                        + "<input id=\"customInput\" type=\"text\" placeholder=\"เช่น 192.168.1.101:8866\" value=\"" + lanUrl.replace("http://", "").replace("/static/remote.html", "") + "\" />"
                        + "<button class=\"btn btn-sec\" onclick=\"AppHost.setServerUrl(document.getElementById('customInput').value)\">💾 ตั้งค่า IP เองและเชื่อมต่อ</button>"
                        + "</div>"
                        + "<div class=\"small-note\">เน็ต 5G / นอกบ้าน: กดปุ่มเชื่อมต่อผ่าน Tailscale</div>"
                        + "</div></body></html>";

                view.loadDataWithBaseURL(currentUrl, errorHtml, "text/html", "utf-8", null);
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(
                    WebView webView,
                    ValueCallback<Uri[]> callback,
                    FileChooserParams fileChooserParams) {
                if (filePathCallback != null) {
                    filePathCallback.onReceiveValue(null);
                }
                filePathCallback = callback;
                try {
                    Intent intent = fileChooserParams.createIntent();
                    intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, false);
                    startActivityForResult(intent, FILE_CHOOSER_REQUEST_CODE);
                } catch (Exception e) {
                    filePathCallback = null;
                    callback.onReceiveValue(null);
                    return false;
                }
                return true;
            }
        });

        web.loadUrl(getCurrentServerUrl());
    }

    private String getCurrentServerUrl() {
        SharedPreferences prefs = getSharedPreferences(PREF_NAME, MODE_PRIVATE);
        return prefs.getString(KEY_SERVER_URL, getString(R.string.start_url));
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (intent != null && intent.getData() != null && web != null) {
            web.loadUrl(intent.getDataString());
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == FILE_CHOOSER_REQUEST_CODE && filePathCallback != null) {
            filePathCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data));
            filePathCallback = null;
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK && web.canGoBack()) {
            web.goBack();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.destroy();
        }
        super.onDestroy();
    }
}
