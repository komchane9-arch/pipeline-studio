package th.pipeline.links;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.CookieManager;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

public class MainActivity extends Activity {
    private static final String DEFAULT_SERVER = "https://laptop-ipb0ansq.tailcb70ec.ts.net";
    private WebView web;
    private TextView status;
    private String server;
    private String pendingShare = "";

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        server = getPreferences(MODE_PRIVATE).getString("server", DEFAULT_SERVER);
        LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.VERTICAL);
        LinearLayout toolbar = new LinearLayout(this);
        Button home = new Button(this); home.setText("คลังลิงก์"); home.setOnClickListener(v -> openLibrary());
        Button reload = new Button(this); reload.setText("โหลดใหม่"); reload.setOnClickListener(v -> web.reload());
        Button settings = new Button(this); settings.setText("เชื่อมต่อ"); settings.setOnClickListener(v -> settings());
        toolbar.addView(home); toolbar.addView(reload); toolbar.addView(settings);
        layout.addView(toolbar);
        status = new TextView(this); status.setTextSize(12); status.setPadding(16,4,16,8); layout.addView(status);
        web = new WebView(this); layout.addView(web,new LinearLayout.LayoutParams(-1,0,1)); setContentView(layout);
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setDomStorageEnabled(true);
        web.getSettings().setAllowFileAccess(false);
        web.getSettings().setAllowContentAccess(false);
        CookieManager.getInstance().setAcceptCookie(true);
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (sameServer(uri)) return false;
                if ("https".equals(uri.getScheme()) || "http".equals(uri.getScheme())) {
                    try { startActivity(new Intent(Intent.ACTION_VIEW,uri)); }
                    catch (Exception e) { Toast.makeText(MainActivity.this,"เปิดลิงก์ไม่ได้",Toast.LENGTH_SHORT).show(); }
                }
                return true;
            }
            @Override public void onPageFinished(WebView view,String url) {
                CookieManager.getInstance().flush();
                if (url.startsWith(server + "/static/link-library.html") && !pendingShare.isEmpty()) {
                    String text=pendingShare; pendingShare="";
                    view.evaluateJavascript("location.hash='share='+encodeURIComponent("+org.json.JSONObject.quote(text)+")",null);
                }
            }
            @Override public void onReceivedError(WebView view,WebResourceRequest request,WebResourceError error) {
                if (request.isForMainFrame()) status.setText("เชื่อมต่อไม่ได้ · กดเชื่อมต่อเพื่อตั้งค่า หรือเปิด Tailscale");
            }
        });
        receive(getIntent()); openLibrary();
    }
    private boolean sameServer(Uri uri) {
        Uri base=Uri.parse(server);
        return base.getScheme().equals(uri.getScheme()) && base.getHost().equals(uri.getHost()) && base.getPort()==uri.getPort();
    }
    private void receive(Intent intent) {
        if (Intent.ACTION_SEND.equals(intent.getAction())) {
            String value=intent.getStringExtra(Intent.EXTRA_TEXT);
            if (value!=null) pendingShare=value.substring(0,Math.min(value.length(),20000));
        }
    }
    @Override protected void onNewIntent(Intent intent) { super.onNewIntent(intent); setIntent(intent); receive(intent); openLibrary(); }
    private void openLibrary() { status.setText(server); web.loadUrl(server+"/static/link-library.html"); }
    private void setServer(String value) {
        try {
            String clean=value.trim(); if(!clean.contains("://")) clean="http://"+clean;
            Uri uri=Uri.parse(clean);
            if (!("http".equals(uri.getScheme()) || "https".equals(uri.getScheme())) || uri.getHost()==null || uri.getUserInfo()!=null) throw new IllegalArgumentException();
            server=uri.getScheme()+"://"+uri.getEncodedAuthority();
            getPreferences(MODE_PRIVATE).edit().putString("server",server).apply(); openLibrary();
        } catch(Exception e) { Toast.makeText(this,"ใส่ URL เซิร์ฟเวอร์ เช่น http://192.168.1.101:8866",Toast.LENGTH_LONG).show(); }
    }
    private void settings() {
        final EditText input=new EditText(this); input.setSingleLine(true); input.setText(server);
        new AlertDialog.Builder(this).setTitle("เชื่อมต่อ Pipeline Studio").setMessage("ใช้ Tailscale นอกบ้าน หรือใส่ IP คอมเมื่ออยู่ Wi-Fi เดียวกัน")
            .setView(input).setPositiveButton("บันทึก",(d,w)->setServer(input.getText().toString()))
            .setNeutralButton("USB",(d,w)->setServer("http://127.0.0.1:8866"))
            .setNegativeButton("Tailscale",(d,w)->setServer(DEFAULT_SERVER)).show();
    }
    @Override public void onBackPressed() { if(web.canGoBack()) web.goBack(); else super.onBackPressed(); }
    @Override protected void onDestroy() { web.destroy(); super.onDestroy(); }
}
