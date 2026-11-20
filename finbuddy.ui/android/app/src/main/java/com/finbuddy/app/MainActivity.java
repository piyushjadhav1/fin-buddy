package com.finbuddy.app;

import android.app.Activity;
import android.app.NotificationManager;
import android.content.ComponentName;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.view.View;

import androidx.webkit.WebViewAssetLoader;
import androidx.webkit.WebViewClientCompat;

public final class MainActivity extends Activity {
    private WebView webView;
    private WebViewAssetLoader assetLoader;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(0xFF075B4D);
        getWindow().setNavigationBarColor(0xFFFFFFFF);

        webView = new WebView(this);
        webView.setBackgroundColor(0xFFF4F7FB);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);

        assetLoader = new WebViewAssetLoader.Builder()
                .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this))
                .build();
        webView.setWebViewClient(new WebViewClientCompat() {
            @Override
            public android.webkit.WebResourceResponse shouldInterceptRequest(
                    WebView view, WebResourceRequest request) {
                return assetLoader.shouldInterceptRequest(request.getUrl());
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                return !"appassets.androidplatform.net".equals(uri.getHost());
            }
        });
        webView.addJavascriptInterface(new FinBuddyBridge(), "FinBuddyAndroid");
        setContentView(webView);
        webView.loadUrl("https://appassets.androidplatform.net/assets/index.html");
    }

    @Override
    protected void onResume() {
        super.onResume();
        CaptureQueue.retryConfigurationFailures(this);
        TransactionSyncScheduler.enqueue(this);
        if (webView != null) {
            webView.post(() -> webView.evaluateJavascript("refreshAndroidCaptureStatus();", null));
        }
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }

    private boolean hasNotificationAccess() {
        NotificationManager manager = getSystemService(NotificationManager.class);
        return manager != null && manager.isNotificationListenerAccessGranted(
                new ComponentName(this, UpiNotificationListener.class));
    }

    private void setSystemBarsDark(boolean dark) {
        getWindow().setStatusBarColor(dark ? 0xFF000000 : 0xFF1265F3);
        getWindow().setNavigationBarColor(dark ? 0xFF000000 : 0xFFFFFFFF);
        View decor = getWindow().getDecorView();
        int flags = decor.getSystemUiVisibility() & ~View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
        if (!dark) flags |= View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
        decor.setSystemUiVisibility(flags);
    }

    private final class FinBuddyBridge {
        @JavascriptInterface
        public boolean hasNotificationAccess() {
            return MainActivity.this.hasNotificationAccess();
        }

        @JavascriptInterface
        public void setDarkMode(boolean dark) {
            runOnUiThread(() -> MainActivity.this.setSystemBarsDark(dark));
        }

        @JavascriptInterface
        public void openNotificationAccessSettings() {
            runOnUiThread(() -> startActivity(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)));
        }

        @JavascriptInterface
        public String peekPendingTransactions() {
            return CaptureQueue.peek(MainActivity.this).toString();
        }

        @JavascriptInterface
        public void acknowledgeTransaction(String notificationId) {
            CaptureQueue.acknowledge(MainActivity.this, notificationId);
        }
    }
}
