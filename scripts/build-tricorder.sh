#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${1:-/apps/solomonprime-development/tricorder-prime}"
[[ -d "$ROOT" && -x "$ROOT/gradlew" ]] || { echo "Tricorder source unavailable: $ROOT" >&2; exit 2; }
[[ -n "${ANDROID_HOME:-}" || -s "$ROOT/local.properties" ]] || {
  echo 'Set ANDROID_HOME or create local.properties with sdk.dir before building.' >&2; exit 2;
}
(cd "$ROOT" && ./gradlew --no-daemon testDebugUnitTest assembleDebug)
APK="$ROOT/app/build/outputs/apk/debug/app-debug.apk"
[[ -s "$APK" ]] || { echo 'Debug APK was not produced.' >&2; exit 3; }
sha256sum "$APK"
echo "Unsigned debug APK: $APK"
echo 'Production signing keys are intentionally local and are never packaged or uploaded.'
