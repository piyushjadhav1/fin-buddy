package com.finbuddy.app;

import android.app.Notification;
import android.os.Bundle;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class UpiNotificationListener extends NotificationListenerService {
    private static final List<String> SUPPORTED_PACKAGES = Arrays.asList(
            "com.google.android.apps.nbu.paisa.user", // Google Pay India
            "com.phonepe.app",                       // PhonePe
            "net.one97.paytm",                       // Paytm
            "in.org.npci.upiapp"                     // BHIM
    );

    private static final Pattern CURRENCY_AMOUNT = Pattern.compile(
            "(?i)(?:₹|rs\\.?|inr)\\s*([0-9][0-9,]*(?:\\.[0-9]{1,2})?)");
    private static final Pattern VERBAL_AMOUNT = Pattern.compile(
            "(?i)\\b(?:paid|debited|sent|spent|payment of|amount)\\D{0,20}([0-9][0-9,]*(?:\\.[0-9]{1,2})?)");
    private static final Pattern[] MERCHANT_PATTERNS = {
            Pattern.compile("(?i)\\b(?:paid|sent|payment)\\s+(?:₹?\\s*[0-9,.]+\\s+)?to\\s+([^\\n|,;]{2,60})"),
            Pattern.compile("(?i)\\b(?:to|at|merchant)\\s+([^\\n|,;]{2,60})")
    };
    private static final Pattern UPI_ID = Pattern.compile("(?i)\\b[\\w.\\-]+@[\\w]+\\b");

    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        if (sbn == null || !SUPPORTED_PACKAGES.contains(sbn.getPackageName())) return;

        String text = notificationText(sbn.getNotification());
        if (text.isEmpty()) return;
        String normalized = text.toLowerCase(Locale.ROOT);

        // Ignore incoming transfers, refunds and requests; this listener records expenses only.
        if (contains(normalized, "received", "credited", "refund", "cashback", "requested", "collect request")) return;
        if (!contains(normalized, "paid", "debited", "sent", "spent", "payment successful",
                "transaction successful", "money sent", "transferred")) return;

        Double amount = findAmount(text);
        String merchant = findMerchant(text);
        if (amount == null || amount <= 0 || merchant.isEmpty()) return;

        String date = Instant.ofEpochMilli(sbn.getPostTime())
                .atZone(ZoneId.systemDefault()).toLocalDate().toString();
        String notificationId = stableId(sbn.getPackageName() + "|" + sbn.getKey() + "|" +
                sbn.getPostTime() + "|" + amount + "|" + merchant);
        try {
            JSONObject item = new JSONObject();
            item.put("notificationId", notificationId);
            item.put("externalId", "android:" + notificationId);
            item.put("merchant", merchant);
            item.put("amount", amount);
            item.put("date", date);
            CaptureQueue.add(this, item);
        } catch (Exception ignored) {
            // A malformed notification is skipped; notification contents are never uploaded.
        }
    }

    private static String notificationText(Notification notification) {
        Bundle extras = notification.extras;
        if (extras == null) return "";
        List<String> parts = new ArrayList<>();
        add(parts, extras.getCharSequence(Notification.EXTRA_TITLE));
        add(parts, extras.getCharSequence(Notification.EXTRA_TEXT));
        add(parts, extras.getCharSequence(Notification.EXTRA_BIG_TEXT));
        CharSequence[] lines = extras.getCharSequenceArray(Notification.EXTRA_TEXT_LINES);
        if (lines != null) for (CharSequence line : lines) add(parts, line);
        return String.join(" | ", parts);
    }

    private static void add(List<String> parts, CharSequence value) {
        if (value == null) return;
        String text = value.toString().trim();
        if (!text.isEmpty() && !parts.contains(text)) parts.add(text);
    }

    private static boolean contains(String text, String... needles) {
        for (String needle : needles) if (text.contains(needle)) return true;
        return false;
    }

    private static Double findAmount(String text) {
        Matcher matcher = CURRENCY_AMOUNT.matcher(text);
        if (!matcher.find()) matcher = VERBAL_AMOUNT.matcher(text);
        if (!matcher.find(0)) return null;
        try {
            return Double.parseDouble(matcher.group(1).replace(",", ""));
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    private static String findMerchant(String text) {
        for (Pattern pattern : MERCHANT_PATTERNS) {
            Matcher matcher = pattern.matcher(text);
            if (matcher.find()) {
                String merchant = matcher.group(1)
                        .replaceAll("(?i)\\s+(?:via|using|on|dated|ref|upi|card|txn|transaction).*", "")
                        .replaceAll("(?i)\\b(?:successful|successfully|completed)\\b.*", "")
                        .trim();
                merchant = UPI_ID.matcher(merchant).replaceAll("").replaceAll("[.\\-–—:]+$", "").trim();
                if (merchant.length() > 60) merchant = merchant.substring(0, 60).trim();
                if (merchant.length() >= 2) return merchant;
            }
        }
        return "";
    }

    private static String stableId(String value) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
            StringBuilder result = new StringBuilder();
            for (int i = 0; i < 16; i++) result.append(String.format(Locale.ROOT, "%02x", digest[i]));
            return result.toString();
        } catch (Exception ignored) {
            return Integer.toHexString(value.hashCode());
        }
    }
}
