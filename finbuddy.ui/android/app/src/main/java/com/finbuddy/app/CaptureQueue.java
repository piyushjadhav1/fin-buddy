package com.finbuddy.app;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

final class CaptureQueue {
    private static final String PREFS = "finbuddy_capture_queue";
    private static final String KEY = "pending";
    private static final int MAX_PENDING = 500;
    static final int MAX_RETRIES = 8;

    private CaptureQueue() {}

    static synchronized boolean add(Context context, JSONObject transaction) {
        return add(context, transaction, "pending", null);
    }

    static synchronized boolean addForReview(Context context, JSONObject transaction, String reason) {
        return add(context, transaction, "failed", reason);
    }

    private static boolean add(Context context, JSONObject transaction, String status, String error) {
        JSONArray queue = read(context);
        String notificationId = transaction.optString("notificationId");
        for (int i = 0; i < queue.length(); i++) {
            JSONObject item = queue.optJSONObject(i);
            if (item != null && notificationId.equals(item.optString("notificationId"))) return true;
        }
        if (queue.length() >= MAX_PENDING) return false;
        try {
            transaction.put("sync_status", status);
            transaction.put("retry_count", 0);
            transaction.put("last_error", error == null ? JSONObject.NULL : error);
            transaction.put("ui_acknowledged", false);
        } catch (JSONException ignored) {
            return false;
        }
        queue.put(transaction);
        write(context, queue);
        return true;
    }

    static synchronized JSONArray peek(Context context) {
        return read(context);
    }

    static synchronized JSONArray pendingForSync(Context context) {
        JSONArray current = read(context);
        JSONArray pending = new JSONArray();
        for (int i = 0; i < current.length(); i++) {
            JSONObject item = current.optJSONObject(i);
            if (item != null && "pending".equals(item.optString("sync_status"))
                    && !item.optString("raw_text").isEmpty()) {
                try {
                    pending.put(new JSONObject(item.toString()));
                } catch (JSONException ignored) {
                    // Leave malformed records in the durable queue for inspection.
                }
            }
        }
        return pending;
    }

    static synchronized void acknowledge(Context context, String notificationId) {
        JSONArray current = read(context);
        JSONArray remaining = new JSONArray();
        for (int i = 0; i < current.length(); i++) {
            JSONObject item = current.optJSONObject(i);
            if (item == null) continue;
            if (!notificationId.equals(item.optString("notificationId"))) {
                remaining.put(item);
                continue;
            }
            // The unchanged WebView calls this after saving its local copy. Keep
            // the server queue until the API also confirms, or until both sides do.
            try {
                item.put("ui_acknowledged", true);
                if (!"synced".equals(item.optString("sync_status"))
                        && !item.optString("raw_text").isEmpty()) remaining.put(item);
            } catch (JSONException ignored) {
                remaining.put(item);
            }
        }
        write(context, remaining);
    }

    static synchronized void markSynced(Context context, String notificationId) {
        update(context, notificationId, true, null, false);
    }

    static synchronized void recordFailure(Context context, String notificationId,
                                           String message, boolean retryable) {
        update(context, notificationId, false, message, retryable);
    }

    static synchronized void markPendingFailed(Context context, String message) {
        JSONArray current = read(context);
        for (int i = 0; i < current.length(); i++) {
            JSONObject item = current.optJSONObject(i);
            if (item != null && "pending".equals(item.optString("sync_status"))) {
                try {
                    item.put("sync_status", "failed");
                    item.put("last_error", message);
                    item.put("retry_count", MAX_RETRIES);
                } catch (JSONException ignored) {
                    // Keep the original item if it cannot be updated.
                }
            }
        }
        write(context, current);
    }

    static synchronized void retryConfigurationFailures(Context context) {
        JSONArray current = read(context);
        for (int i = 0; i < current.length(); i++) {
            JSONObject item = current.optJSONObject(i);
            if (item == null || !"failed".equals(item.optString("sync_status"))) continue;
            String error = item.optString("last_error");
            boolean retryable = error.startsWith("Backend authentication")
                    || error.startsWith("Backend address is not configured")
                    || error.startsWith("Release builds require an HTTPS")
                    || error.startsWith("Upload retry limit reached");
            if (retryable) {
                try {
                    item.put("sync_status", "pending");
                    item.put("retry_count", 0);
                    item.put("last_error", JSONObject.NULL);
                } catch (JSONException ignored) {
                    // Preserve the failed queue entry if it cannot be updated.
                }
            }
        }
        write(context, current);
    }

    private static void update(Context context, String notificationId, boolean synced,
                               String message, boolean retryable) {
        JSONArray current = read(context);
        JSONArray remaining = new JSONArray();
        for (int i = 0; i < current.length(); i++) {
            JSONObject item = current.optJSONObject(i);
            if (item == null) continue;
            if (!notificationId.equals(item.optString("notificationId"))) {
                remaining.put(item);
                continue;
            }
            if (synced) {
                try {
                    item.put("sync_status", "synced");
                    item.put("raw_text", "");
                    item.put("last_error", JSONObject.NULL);
                    if (!item.optBoolean("ui_acknowledged", false)) remaining.put(item);
                } catch (JSONException ignored) {
                    remaining.put(item);
                }
            } else {
                int retries = item.optInt("retry_count", 0) + 1;
                try {
                    item.put("retry_count", retries);
                    item.put("last_error", message == null ? JSONObject.NULL : message);
                    item.put("sync_status", retryable && retries < MAX_RETRIES ? "pending" : "failed");
                } catch (JSONException ignored) {
                    // Preserve the item rather than losing a notification on an update error.
                }
                remaining.put(item);
            }
        }
        write(context, remaining);
    }

    private static JSONArray read(Context context) {
        String saved = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getString(KEY, "[]");
        try {
            return new JSONArray(saved);
        } catch (JSONException ignored) {
            return new JSONArray();
        }
    }

    private static void write(Context context, JSONArray queue) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        prefs.edit().putString(KEY, queue.toString()).commit();
    }
}
