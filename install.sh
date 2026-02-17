#!/bin/bash
set -e

echo "🤖 Claude Code Session Tracker - Installation"
echo "=============================================="
echo ""

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed."
    echo "   Install it from: https://www.python.org/downloads/"
    exit 1
fi

echo "✓ Python 3 found"

# Install dependencies
echo ""
echo "📦 Installing dependencies..."
pip3 install -r requirements.txt

# Make tracker executable
chmod +x claude-tracker.py

# Create launch agent for auto-start (optional)
read -p "Do you want Claude Tracker to start automatically on login? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    PLIST_PATH=~/Library/LaunchAgents/com.claude-tracker.plist
    SCRIPT_PATH="$(pwd)/claude-tracker.py"
    
    cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claude-tracker</string>
    <key>ProgramArguments</key>
    <array>
        <string>$SCRIPT_PATH</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
EOF
    
    launchctl load "$PLIST_PATH"
    echo "✓ Auto-start configured"
fi

echo ""
echo "✅ Installation complete!"
echo ""
echo "To start the tracker:"
echo "  ./claude-tracker.py"
echo ""
echo "Look for the 🤖 icon in your menu bar!"
