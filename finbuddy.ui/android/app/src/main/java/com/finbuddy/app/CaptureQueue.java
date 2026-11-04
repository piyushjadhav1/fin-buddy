package com.finbuddy.app;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

final class CaptureQueue {
    private static final String PREFS = "finbuddy_capture_queue";
    private static final String KEY = "pending";
    private static final int MAX_PENDING = 100;

    private CaptureQueue() {}

    static synchronized void add(Context context, JSONObject transaction) {
        JSONArray queue = read(context);
        String notificationId = transaction.optString("notificationId");
        for (int i = 0; i < queue.length(); i++) {
            JSONObject item = queue.optJSONObject(i);
            if (item != null && notificationId.equals(item.optString("notificationId"))) return;
        }
        queue.put(transaction);
        while (queue.length() > MAX_PENDING) queue.remove(0);
        write(context, queue);
    }

    static synchronized JSONArray peek(Context context) {
        return read(context);
    }

    static synchronized void acknowledge(Context context, String notificationId) {
        JSONArray current = read(context);
        JSONArray remaining = new JSONArray();
        for (int i = 0; i < current.length(); i++) {
            JSONObject item = current.optJSONObject(i);
            if (item != null && !notificationId.equals(item.optString("notificationId"))) {
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
        prefs.edit().putString(KEY, queue.toString()).apply();
    }
}
