# FinBuddy Android app

This Java Android app loads the supplied screen in a WebView and optionally captures outgoing payment notifications. Captured notification transactions are kept in an app-private queue, shown in the existing Android WebView UI, and uploaded by WorkManager to the existing FastAPI endpoint. The server saves them through the existing FinBuddy SQLite data layer.

## Build and run

1. Install Android Studio with JDK 17 and Android SDK Platform 35.
2. Open this `android` folder in Android Studio and sync Gradle. The project uses Android Gradle Plugin 8.7.3 and Gradle 8.9, the compatible wrapper version for that plugin.
3. Start the FastAPI backend from `beckend 3` using the existing database. For safe development, set `FINBUDDY_DB` to a disposable copy of the SQLite database before starting the server. Do not use the team's working database for test writes. For a physical device, start Uvicorn with `--host 0.0.0.0` on a trusted development network and allow the port through the computer's firewall; the device and computer must be on the same network.
4. For the Android emulator, the debug backend address defaults to `http://10.0.2.2:8000`. For a physical device on the same network, set `FINBUDDY_DEBUG_BASE_URL` to the development computer's LAN URL before Gradle sync/build, for example `http://192.168.x.x:8000` after the team supplies its actual address. Do not commit a machine-specific address.
5. Build/install the `debug` variant. Debug builds allow HTTP only for local development. Release builds require a configured HTTPS URL and the worker rejects non-HTTPS release addresses.
6. In FinBuddy, open **Settings → Automatic UPI capture → Set up** and grant Notification Access. Make a small test payment only when using the disposable database, then check the server database and the app's transaction view.

Example PowerShell override for a debug build (replace the example with the team's actual LAN address):

```powershell
$env:FINBUDDY_DEBUG_BASE_URL = "http://192.168.x.x:8000"
cd path\to\fin-buddy-main\finbuddy.ui\android
.\gradlew.bat assembleDebug
```

For a release build, provide `FINBUDDY_RELEASE_BASE_URL` as an HTTPS URL through a protected build environment. Do not put a shared production API token in Gradle, Java source, or the APK.

## Notification-to-database flow

```text
Supported payment notification
  -> Java notification listener and parser
  -> app-private SharedPreferences queue
  -> WorkManager (network connected, unique work, exponential backoff)
  -> POST /api/transactions
  -> FastAPI validation
  -> existing FinBuddy SQLite data layer
```

The queued request contains exactly the existing six transaction fields: `raw_text`, `amount` (INR rupees with up to two decimals), `date` (`YYYY-MM-DD`), `txn_type` (`debit`), `merchant`, and `category`. Category is selected using the same starter keyword groups as the backend where possible, with `Others` as the fallback. Incoming payments and refunds are still ignored; this listener does not fabricate credits.

If an outgoing-payment notification lacks a confident amount or merchant, or has a clearly non-INR currency, the app keeps a local failed/review queue item containing its raw text and reason. It is not uploaded or treated as an INR expense. The unchanged UI has no review/edit screen for these records yet; they remain on-device until the app data is cleared. Unrecognized formats that do not look like outgoing payments are ignored.

The WebView continues to receive captured items through its existing JavaScript bridge and stores its own local view data. Its acknowledgement now means “saved in this WebView,” not “saved on the server.” The native queue remains until the API confirms the transaction too. This preserves the existing HTML files and allows the upload to continue when the WebView is closed.

`raw_text` is needed by the current API. The notification text is held in app-private SharedPreferences until a successful API response, is not written to logs, and is cleared from the queue after confirmation. SharedPreferences is not encrypted by default. Only notifications from the configured payment package IDs are considered, but granting Notification Access allows Android's listener to observe notifications from other apps; processing remains filtered on-device.

## Retry and duplicate behavior

- The queue stores `sync_status`, `retry_count`, `last_error`, and whether the WebView has saved its copy.
- The app-private queue is capped at 500 items; it no longer evicts older unsynced entries, but new capture is skipped if the queue is full.
- Re-delivery of a notification with the same local notification ID is ignored while its queue entry exists.
- WorkManager requires network access, uses unique chained work, exponential backoff, and stops after eight worker attempts. Validation/authentication failures remain in the local queue as failed records.
- The server API has no idempotency key and the unchanged database does not uniquely constrain notification IDs. If the server stores a transaction but the response is lost, a retry may create a duplicate. This implementation does not claim durable server-side deduplication.
- If `FINBUDDY_API_TOKEN` is enabled, Android uploads receive `401` because the app has no trusted login/token flow. Do not embed the shared token in the APK. Use a controlled local demo with token protection disabled, or later design proper user authentication/a trusted gateway.

## API and database

The worker uses the existing `POST /api/transactions` route and the existing database layer. It does not create a new database, change the schema, run migrations, or add a batch endpoint. The current Android WebView's own relative `/api/...` calls still target its local asset origin; this change specifically connects captured notification records to the backend. Manual Android UI operations remain local unless a separate UI/network integration is approved.

## Build and verification status

The Android project requires JDK 17 and Android SDK Platform 35. Build with:

```powershell
.\gradlew.bat assembleDebug
```

For API writes, run the backend against a disposable database copy and verify `GET /api/health`, one synthetic POST, and the resulting row in that copy. The live `finbuddy.ui\finbuddy\data\app.sqlite3` must not be used for write tests. Device checks should cover offline queue retention, reconnection/upload, repeated notification delivery, and API validation rejection.

Live notification formats vary by payment app, and parser accuracy has not been confirmed on a physical device. This is a prototype capture path rather than a bank feed. No deployment URL is configured; release builds need a team-provided HTTPS URL. A public deployment with `FINBUDDY_API_TOKEN` enabled needs an approved authentication design before Android uploads can work.
