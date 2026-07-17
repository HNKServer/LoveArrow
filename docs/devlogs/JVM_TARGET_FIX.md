# JVM target compatibility fix

If Android Studio reports:

```
Inconsistent JVM-target compatibility detected for tasks 'compileDebugJavaWithJavac' (1.8) and 'compileDebugKotlin' (21)
```

make Java and Kotlin use the same JVM target. This project pins both to Java 17:

```gradle
android {
    compileOptions {
        sourceCompatibility JavaVersion.VERSION_17
        targetCompatibility JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = '17'
    }
}

kotlin {
    jvmToolchain(17)
}
```

Java 17 is the safest target for modern Android Gradle Plugin builds. It avoids Kotlin inheriting the host JDK 21 target while Javac remains on 1.8.
