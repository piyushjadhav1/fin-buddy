# FinBuddy Android app

This Android Studio project wraps the supplied FinBuddy screen in an offline Android app and adds an optional notification listener for expense capture. The Python/SQLite backend currently serves the web version only; this Android wrapper does not connect to that server.

## Build and run

1. Install Android Studio with its bundled JDK 17 and Android SDK Platform 35.
2. Open this `android` folder in Android Studio and let Gradle sync. The project uses Android Gradle Plugin 8.7.3 and Gradle 8.9.
3. Connect an Android phone (minimum Android 8.1 / API 27), choose **Run**, and install FinBuddy.
4. In FinBuddy, open **Settings → Automatic UPI capture → Set up**. Review Android's Notification access screen and enable FinBuddy only if you want capture. Return to FinBuddy; the setting status will update.
5. Make a small test payment using an installed supported app and check the Transactions page. Confirm that the amount, merchant, date and category are correct before relying on the record.

Android Studio is required to build and install the app. This workspace currently has no Android SDK, Gradle installation, or working Java runtime, so no APK could be built here.

## What capture does

- Listens for new notifications from the Google Pay India, PhonePe, Paytm and BHIM package IDs listed in `UpiNotificationListener.java`.
- Filters notifications on the phone for outgoing-payment wording, ignores incoming/refund wording, then tries to parse an amount and merchant.
- Queues only the parsed merchant, amount, local notification date and a deduplication ID in private app storage. Raw notification text is not sent to a server or retained in the queue.
- Passes queued records to the existing page, which categorizes them and updates transaction history, dashboard totals and the monthly spending chart. The page stores its data in that Android WebView's local storage.

Notification access is a powerful Android permission: Android lets the listener observe notifications across apps. FinBuddy processes only the four package IDs above, on-device. The listener is optional and can be disabled at any time in Android Settings. This project has no network permission and no backend. Cross-device sync or cloud backup would need a separately designed backend and privacy controls.

## Limits

This is best-effort notification parsing, not a bank feed or UPI integration. Capture works only when the payment app posts a readable notification in a format the parser recognizes. It can miss transactions, misread details, or stop matching when an app changes its notification wording or package ID. The recorded date is the notification's posted date, which can differ from the actual payment date. Transactions without a clear outgoing-payment signal, amount, or merchant are skipped. Check captured records and keep statements or receipts as the authoritative history.

The package IDs identify the currently listed Android apps, but their notification formats have not been verified against live payments on a device. Do not describe this as universal capture.
