#!/usr/bin/env bash
set -e

PLIST_PATH="$HOME/Library/LaunchAgents/com.robknightstrong.sanctuary.plist"
APP_DIR="/Users/student/Library/CloudStorage/GoogleDrive-robknightstrong@gmail.com/My Drive/AuDHD-Assistant"
LOG_DIR="$HOME/Library/Logs/SanctuaryAssistant"

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$LOG_DIR"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.robknightstrong.sanctuary</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>-m</string>
        <string>backend.main</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${APP_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/sanctuary.out.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/sanctuary.err.log</string>
</dict>
</plist>
EOF

echo "✅ Installed macOS 24/7 auto-start agent at: $PLIST_PATH"
echo "To activate after reboot or login: launchctl load -w \"$PLIST_PATH\""
