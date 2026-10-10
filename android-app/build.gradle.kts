plugins {
    id("com.android.application") version "8.7.2" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
    // :moonlight-adapter is plain Kotlin JVM, not Android -- a different plugin ID from the
    // one above even though both come from the Kotlin Gradle Plugin family. Declaring it
    // here too, centrally, is required: a subproject applying it with its own explicit
    // version (the original mistake here) rather than inheriting a version pinned in the
    // root is a well-known source of plugin version conflicts in a multi-module build.
    id("org.jetbrains.kotlin.jvm") version "1.9.24" apply false
}
