#!/bin/bash
set -e

echo "ClaudeWatch - Installation"
echo "=========================="
echo ""

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed."
    echo "  Install it from: https://www.python.org/downloads/"
    exit 1
fi

echo "Python 3 found"

# Install dependencies
echo ""
echo "Installing dependencies..."
pip3 install -r requirements.txt

echo "Dependencies installed (rumps, psutil, watchdog)"

# Create launch agent for auto-start (optional)
read -p "Do you want ClaudeWatch to start automatically on login? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    PLIST_PATH=~/Library/LaunchAgents/com.claudewatch.plist
    APP_DIR="$(cd "$(dirname "$0")" && pwd)"

    cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claudewatch</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>-m</string>
        <string>claudewatch</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$APP_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>$APP_DIR</string>
    </dict>
</dict>
</plist>
EOF

    launchctl load "$PLIST_PATH"
    echo "Auto-start configured"
fi

echo ""
echo "Installation complete!"
echo ""
echo "To start ClaudeWatch:"
echo "  python3 -m claudewatch"
echo ""
echo "Or build the standalone app:"
echo "  python3 setup.py py2app"
echo "  open dist/ClaudeWatch.app"
