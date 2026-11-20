package com.finbuddy.app;

import android.content.Context;

import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

public final class TransactionSyncWorker extends Worker {
    private static final int CONNECT_TIMEOUT_MS = 10_000;
    private static final int READ_TIMEOUT_MS = 15_000;

    public TransactionSyncWorker(@NonNull Context context, @NonNull WorkerParameters params) {
        super(context, params);
    }

    @NonNull
    @Override
    public Result doWork() {
        Context context = getApplicationContext();
        JSONArray pending = CaptureQueue.pendingForSync(context);
        if (pending.length() == 0) return Result.success();

        if (getRunAttemptCount() >= CaptureQueue.MAX_RETRIES) {
            CaptureQueue.markPendingFailed(context, "Upload retry limit reached. Open FinBuddy after checking the backend connection.");
            return Result.success();
        }

        String baseUrl = BuildConfig.BACKEND_BASE_URL.trim();
        if (baseUrl.isEmpty()) {
            CaptureQueue.markPendingFailed(context, "Backend address is not configured.");
            return Result.success();
        }
        if (!BuildConfig.DEBUG && !baseUrl.regionMatches(true, 0, "https://", 0, 8)) {
            CaptureQueue.markPendingFailed(context, "Release builds require an HTTPS backend address.");
            return Result.success();
        }

        for (int i = 0; i < pending.length(); i++) {
            JSONObject item = pending.optJSONObject(i);
            if (item == null) continue;
            String notificationId = item.optString("notificationId");
            try {
                JSONObject body = requestBody(item);
                int status = post(baseUrl, body);
                if (status >= 200 && status < 300) {
                    CaptureQueue.markSynced(context, notificationId);
                } else if (status == 401 || status == 403) {
                    CaptureQueue.recordFailure(context, notificationId,
                            "Backend authentication rejected this upload. Configure an approved client authentication flow.", false);
                    CaptureQueue.markPendingFailed(context,
                            "Backend authentication rejected this upload. Configure an approved client authentication flow.");
                    return Result.success();
                } else if (status == 400 || status == 422) {
                    CaptureQueue.recordFailure(context, notificationId,
                            "Backend rejected the transaction fields (HTTP " + status + "). The queued record was retained.", false);
                } else if (status >= 500 || status == 408 || status == 429) {
                    CaptureQueue.recordFailure(context, notificationId,
                            "Temporary backend response (HTTP " + status + ").", true);
                    if (getRunAttemptCount() + 1 < CaptureQueue.MAX_RETRIES) return Result.retry();
                    CaptureQueue.markPendingFailed(context, "Upload retry limit reached.");
                    return Result.success();
                } else {
                    CaptureQueue.recordFailure(context, notificationId,
                            "Backend returned HTTP " + status + ".", false);
                }
            } catch (IOException exception) {
                CaptureQueue.recordFailure(context, notificationId,
                        "Network upload failed; the transaction remains on this device.", true);
                if (getRunAttemptCount() + 1 < CaptureQueue.MAX_RETRIES) return Result.retry();
                CaptureQueue.markPendingFailed(context, "Upload retry limit reached.");
                return Result.success();
            } catch (JSONException exception) {
                CaptureQueue.recordFailure(context, notificationId,
                        "Queued transaction is incomplete and was kept for review.", false);
            }
        }

        // Catch items added while this worker was uploading the earlier snapshot.
        return CaptureQueue.pendingForSync(context).length() > 0
                ? Result.retry() : Result.success();
    }

    private static JSONObject requestBody(JSONObject item) throws JSONException {
        String rawText = item.optString("raw_text").trim();
        String merchant = item.optString("merchant").trim();
        String date = item.optString("date");
        double amount = item.optDouble("amount", -1);
        String type = item.optString("txn_type");
        String category = item.optString("category");
        if (rawText.isEmpty() || merchant.isEmpty() || amount <= 0
                || !date.matches("\\d{4}-\\d{2}-\\d{2}")
                || !("debit".equals(type) || "credit".equals(type))
                || !isCategory(category)) {
            throw new JSONException("Invalid local transaction");
        }
        JSONObject body = new JSONObject();
        body.put("raw_text", rawText);
        body.put("amount", amount);
        body.put("date", date);
        body.put("txn_type", type);
        body.put("merchant", merchant);
        body.put("category", category);
        return body;
    }

    private static boolean isCategory(String value) {
        return "Food".equals(value) || "Travel".equals(value) || "Shopping".equals(value)
                || "Bills/Recharge".equals(value) || "Fees".equals(value)
                || "Entertainment".equals(value) || "Others".equals(value);
    }

    private static int post(String baseUrl, JSONObject body) throws IOException {
        String endpoint = baseUrl.replaceAll("/+$", "") + "/api/transactions";
        HttpURLConnection connection = (HttpURLConnection) new URL(endpoint).openConnection();
        try {
            connection.setRequestMethod("POST");
            connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
            connection.setReadTimeout(READ_TIMEOUT_MS);
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(bytes.length);
            try (OutputStream output = connection.getOutputStream()) {
                output.write(bytes);
            }
            int status = connection.getResponseCode();
            InputStream response = status >= 400 ? connection.getErrorStream() : connection.getInputStream();
            if (response != null) {
                // Drain response safely without logging server or notification text.
                try (InputStream input = response; ByteArrayOutputStream sink = new ByteArrayOutputStream()) {
                    byte[] buffer = new byte[1024];
                    int read;
                    while ((read = input.read(buffer)) != -1) sink.write(buffer, 0, read);
                }
            }
            return status;
        } finally {
            connection.disconnect();
        }
    }
}
