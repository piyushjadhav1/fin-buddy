plugins {
    id("com.android.application")
}

android {
    namespace = "com.finbuddy.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.finbuddy.app"
        minSdk = 27
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
    }
}

dependencies {
    implementation("androidx.webkit:webkit:1.12.1")
}
