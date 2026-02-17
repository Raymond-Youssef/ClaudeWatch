#!/bin/bash

echo "🤖 ClaudeBoard - Uninstallation"
echo "================================"
echo ""

# Stop the app if running
pkill -f claude-tracker.py 2>/dev/null

# Remove launch agent
if [ -f ~/Library/LaunchAgents/com.claudeboard.plist ]; then
    echo "Removing auto-start configuration..."
    launchctl unload ~/Library/LaunchAgents/com.claudeboard.plist 2>/dev/null
    rm ~/Library/LaunchAgents/com.claudeboard.plist
    echo "✓ Auto-start removed"
fi

# Also clean up old launch agent if present
if [ -f ~/Library/LaunchAgents/com.claude-tracker.plist ]; then
    launchctl unload ~/Library/LaunchAgents/com.claude-tracker.plist 2>/dev/null
    rm ~/Library/LaunchAgents/com.claude-tracker.plist
fi

# Ask about data removal
read -p "Do you want to remove all session data? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf ~/.claudeboard
    rm -rf ~/.claude-tracker
    echo "✓ Session data removed"
else
    echo "Session data kept at ~/.claudeboard"
fi

echo ""
echo "✅ Uninstallation complete!"
echo ""
echo "To reinstall: run ./install.sh"
