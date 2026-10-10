// Plain Kotlin JVM module -- no Android dependency. This is deliberate: the event
// translation logic here (VkKeyMap, MoonlightInputAdapter) is the part most likely to have
// a bug, so it stays testable on a plain JVM with plain JUnit, the same reasoning
// :app's own Protocol.kt already uses. The Android-dependent wiring that calls the real
// moonlight-common-c JNI functions lives in :app instead, where it belongs.
plugins {
    // Version intentionally omitted -- pinned centrally in the root build.gradle.kts
    // instead, alongside org.jetbrains.kotlin.android. Declaring a version here too was
    // the original mistake (see the root file's comment on this same plugin).
    id("org.jetbrains.kotlin.jvm")
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}

tasks.test {
    useJUnit()
}
