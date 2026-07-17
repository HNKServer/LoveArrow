# Fix: registerForActivityResult unresolved

`registerForActivityResult` is provided by `androidx.activity.ComponentActivity` / `Fragment`, not by the platform `android.app.Activity` base class.

This build changes `MainActivity` from:

```kotlin
class MainActivity : Activity()
```

to:

```kotlin
class MainActivity : ComponentActivity()
```

and imports:

```kotlin
import androidx.activity.ComponentActivity
```

The project already depends on:

```gradle
implementation 'androidx.activity:activity-ktx:1.9.3'
```

so no Python-side change is involved.
