# Offline Library

A collection of survival, medical, repair, and reference PDFs and web pages, organized by topic, with an `index.html` front end and a prebuilt search index (`_search`). It works with no internet connection.

The `android/` folder contains a small Android app that opens the library on a phone or tablet.

## Using the library on a computer

Open `index.html` in any modern browser. Everything runs locally.

## Installing on an Android device

There are two parts: copy the library folder to the device, and install the app.

### 1. Copy the library to the device

Copy the whole library folder (the one containing `index.html` and `_search`) to the device's storage, for example `Download/Offline-Library`. Copying over USB or using a file-transfer app both work. Make sure the copy is complete, since the app needs `index.html` and `_search` in the same folder.

### 2. Build the app

The app is built with the plain Android SDK tools. Gradle is not needed.

Prerequisites (Windows):

- **JDK** with `javac`, `jar`, and `keytool` on your `PATH`.
- **Android SDK** with build-tools `35.0.0` and platform `android-35`. Install them with Android Studio's SDK Manager, or `sdkmanager "build-tools;35.0.0" "platforms;android-35"`.
- **Git Bash**, to run the build script.
- Optionally, set `ANDROID_HOME` to your SDK folder. If it is not set, the script uses `%LOCALAPPDATA%\Android\Sdk`.

Build from the repository root:

```bash
bash android/build_apk.sh
```

The signed APK is written to `android/build/OfflineLibrary.apk`.

The first build creates `android/offline-library.keystore`. Keep this file. Android only accepts updates to an app that are signed with the same key, so a new keystore means users have to uninstall the old app first. The keystore is git-ignored and must not be committed.

### 3. Install the APK

1. Copy `OfflineLibrary.apk` to the device.
2. Open it in a file manager. When Android asks, allow installs from that app (**Settings > Apps > Special access > Install unknown apps**).
3. Tap **Install**.

### 4. Open the library in the app

1. Launch **Offline Library**.
2. When prompted, choose the library folder you copied in step 1, the one that contains `index.html`.
3. The app opens the library. Access is saved, so you only need to pick the folder again if you move it or revoke access.

If the app reports that `index.html` was not found, pick the folder that directly contains `index.html` and `_search`.

## Repository layout

| Path | Contents |
| --- | --- |
| `index.html` | Library front end |
| `_search/` | Prebuilt search index |
| `build_search_index.py` | Rebuilds the search index |
| `android/` | Android app source, manifest, and build script |
| Topic folders | PDFs and web pages, grouped by subject |
