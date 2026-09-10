plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.remotehid.server"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.remotehid.server"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")

    // Embedded HTTP/WebSocket server — small, single-purpose, well
    // established for exactly this use case.
    implementation("org.nanohttpd:nanohttpd-websocket:2.3.1")

    testImplementation("junit:junit:4.13.2")
}
