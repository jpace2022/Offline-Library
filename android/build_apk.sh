#!/usr/bin/env bash
# Builds OfflineLibrary.apk with the plain Android SDK tools (no Gradle needed).
# Run from Git Bash:  bash android/build_apk.sh
set -euo pipefail
cd "$(dirname "$0")"

SDK="${ANDROID_HOME:-${LOCALAPPDATA:-}/Android/Sdk}"
BT="$SDK/build-tools/35.0.0"
JAR="$SDK/platforms/android-35/android.jar"
[ -f "$JAR" ] || { echo "android.jar not found at $JAR"; exit 1; }

rm -rf build && mkdir -p build/classes

echo "1/5 manifest"
"$BT/aapt2" link -o build/unsigned.apk -I "$JAR" --manifest AndroidManifest.xml \
  --min-sdk-version 24 --target-sdk-version 35 --version-code 1 --version-name 1.0

echo "2/5 compile"
javac --release 11 -nowarn -cp "$JAR" -d build/classes $(find src -name '*.java')

echo "3/5 dex"
"$BT/d8.bat" --release --min-api 24 --lib "$JAR" --output build $(find build/classes -name '*.class')
(cd build && jar uf0M unsigned.apk classes.dex)

echo "4/5 align"
"$BT/zipalign" -f 4 build/unsigned.apk build/aligned.apk

echo "5/5 sign"
# Keep this keystore: Android only accepts an app update signed with the same key. Do not commit it.
KS=offline-library.keystore
[ -f "$KS" ] || keytool -genkeypair -keystore "$KS" -storepass android -keypass android \
  -alias library -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Offline Library" >/dev/null
"$BT/apksigner.bat" sign --ks "$KS" --ks-pass pass:android --out build/OfflineLibrary.apk build/aligned.apk

echo "Done: android/build/OfflineLibrary.apk"
