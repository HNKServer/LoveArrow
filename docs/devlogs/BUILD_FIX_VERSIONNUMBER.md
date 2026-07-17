# Fix for `org.gradle.util.VersionNumber`

This package updates the Chaquopy Gradle plugin from 16.0.0 to 17.0.0.

If your Android Studio uses Gradle 9.x, older plugins which reference `org.gradle.util.VersionNumber` may fail during Gradle Sync. Chaquopy 17.0.0 adds Android Gradle Plugin 9.0–9.2 support and removes this incompatibility.

If you cannot use Chaquopy 17.0.0, pin the project to Gradle 8.x instead, for example Gradle 8.13 with Android Gradle Plugin 8.7.3.
