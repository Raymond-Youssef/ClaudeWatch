#!/bin/bash

echo "ClaudeWatch - Uninstallation"
echo "============================"
echo ""

# Stop the app if running
pkill -f "ClaudeWatch" 2>/dev/null
pkill -f "python3 -m claudewatch" 2>/dev/null

# Remove launch agent
if [ -f ~/Library/LaunchAgents/com.claudewatch.plist ]; then
    echo "Removing auto-start configuration..."
    launchctl unload ~/Library/LaunchAgents/com.claudewatch.plist 2>/dev/null
    rm ~/Library/LaunchAgents/com.claudewatch.plist
    echo "Auto-start removed"
fi

# Clean up legacy launch agent
if [ -f ~/Library/LaunchAgents/com.claude-tracker.plist ]; then
    launchctl unload ~/Library/LaunchAgents/com.claude-tracker.plist 2>/dev/null
    rm ~/Library/LaunchAgents/com.claude-tracker.plist
fi

# Ask about data removal
read -p "Do you want to remove all session data? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf ~/.claudewatch
    echo "Session data removed"
else
    echo "Session data kept at ~/.claudewatch"
fi

echo ""
echo "Uninstallation complete!"
echo ""
echo "To reinstall: run ./install.sh"
