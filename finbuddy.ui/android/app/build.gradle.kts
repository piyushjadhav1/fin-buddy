plugins {
    id("com.android.application")
}

val debugBackendUrl = providers.gradleProperty("FINBUDDY_DEBUG_BASE_URL")
    .orElse(providers.environmentVariable("FINBUDDY_DEBUG_BASE_URL"))
    .orElse("http://10.0.2.2:8000")
    .get()
val releaseBackendUrl = providers.gradleProperty("FINBUDDY_RELEASE_BASE_URL")
    .orElse(providers.environmentVariable("FINBUDDY_RELEASE_BASE_URL"))
    .orElse("")
    .get()

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

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        getByName("debug") {
            buildConfigField("String", "BACKEND_BASE_URL", "\"$debugBackendUrl\"")
        }
        getByName("release") {
            buildConfigField("String", "BACKEND_BASE_URL", "\"$releaseBackendUrl\"")
        }
    }
}

dependencies {
    implementation("androidx.webkit:webkit:1.12.1")
    implementation("androidx.work:work-runtime:2.10.1")
}
