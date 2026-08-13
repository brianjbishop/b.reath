#!/bin/zsh
# Build b.reath.app — a minimal macOS bundle wrapping the Python entry point.
#
# The dock icon can be set at runtime via AppKit, but the Cmd-Tab switcher and
# the menu bar read the *bundle*, so running as a plain script shows Python's
# rocket and the name "Python". A bundle is the only way to fix those.
#
# Regenerate after changing assets/icon.png.  Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

APP="b.reath.app"
ICON_SRC="assets/icon.png"

[[ -f "$ICON_SRC" ]] || { echo "missing $ICON_SRC"; exit 1; }

rm -rf "$APP" build_iconset.iconset
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" build_iconset.iconset

# macOS wants every size present; iconutil is strict about the naming.
for sz in 16 32 128 256 512; do
  sips -z $sz $sz        "$ICON_SRC" --out "build_iconset.iconset/icon_${sz}x${sz}.png"    >/dev/null
  sips -z $((sz*2)) $((sz*2)) "$ICON_SRC" --out "build_iconset.iconset/icon_${sz}x${sz}@2x.png" >/dev/null
done
iconutil -c icns build_iconset.iconset -o "$APP/Contents/Resources/icon.icns"
rm -rf build_iconset.iconset

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>            <string>b.reath</string>
  <key>CFBundleDisplayName</key>     <string>b.reath</string>
  <key>CFBundleExecutable</key>      <string>breath</string>
  <key>CFBundleIconFile</key>        <string>icon</string>
  <key>CFBundleIdentifier</key>      <string>com.brianjbishop.breath</string>
  <key>CFBundlePackageType</key>     <string>APPL</string>
  <key>CFBundleShortVersionString</key> <string>1.0</string>
  <key>NSHighResolutionCapable</key> <true/>
  <!-- Belt and braces with the arch pin in the launcher: never run translated. -->
  <key>LSRequiresNativeExecution</key> <true/>
  <!-- Bluetooth and local network prompts need a stated purpose or macOS denies them. -->
  <key>NSBluetoothAlwaysUsageDescription</key>
  <string>b.reath receives breath data from TOTEM over Bluetooth.</string>
  <key>NSLocalNetworkUsageDescription</key>
  <string>b.reath receives breath data from phones on your local network.</string>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/breath" <<'LAUNCH'
#!/bin/zsh
# Resolve the project root from inside the bundle: Contents/MacOS -> project.
HERE="${0:A:h}"
ROOT="${HERE:h:h:h}"
cd "$ROOT"

# Force the machine's native architecture.
#
# The framework python is a universal binary, and LaunchServices starts this
# script under x86_64 even on Apple Silicon.  The venv's native extensions
# (dearpygui, python-rtmidi) are arm64-only, so it dies at import with
# "incompatible architecture" — and a double-clicked app has nowhere to print,
# so it just looks like nothing happens.  Terminal inherits the native arch,
# which is why it works there and not here.
#
# `uname -m` is NO USE for this: under Rosetta it reports x86_64 too, so it
# faithfully propagates the wrong answer.  hw.optional.arm64 describes the
# hardware regardless of what the current process is translated to.
if [[ "$(sysctl -n hw.optional.arm64 2>/dev/null)" == "1" ]]; then
  NATIVE_ARCH=arm64
else
  NATIVE_ARCH=x86_64
fi
exec arch -"$NATIVE_ARCH" "$ROOT/.venv/bin/python" -m breath_midi.app
LAUNCH
chmod +x "$APP/Contents/MacOS/breath"

echo "built $APP"
