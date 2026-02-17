# Claude Code Session Tracker 🤖

A lightweight macOS menu bar app that tracks all your Claude Code sessions across different IDEs and terminals.

## Features

✨ **System-wide tracking** - Monitors all `claude-code` processes regardless of where they're launched  
🔔 **Desktop notifications** - Get notified when sessions start and complete  
📊 **Live dashboard** - Click the menu bar icon to see all active sessions  
⏱️ **Runtime tracking** - See how long each session has been running  
🎯 **IDE detection** - Automatically detects which IDE/terminal launched each session  
📈 **Statistics** - Track completed sessions and average runtime  
🪶 **Lightweight** - Minimal resource usage, runs silently in the background

## Installation

### Prerequisites
- macOS
- Python 3.7+
- Claude Code installed

### Quick Install

```bash
# Clone or download these files to a folder
cd claude-tracker

# Run the installer
chmod +x install.sh
./install.sh
```

The installer will:
1. Install required Python packages (`rumps`, `psutil`)
2. Make the tracker executable
3. Optionally configure auto-start on login

### Manual Installation

```bash
pip3 install -r requirements.txt
chmod +x claude-tracker.py
./claude-tracker.py
```

## Usage

### Starting the Tracker

```bash
./claude-tracker.py
```

You'll see a 🤖 icon appear in your menu bar.

### Using Claude Code Normally

Just use `claude-code` as you normally would - from any IDE or terminal:

```bash
claude-code "refactor the authentication module"
```

The tracker will automatically detect and track the session!

### Menu Bar Features

Click the 🤖 icon to:
- **View active sessions** - See all running sessions with runtime and IDE
- **Click a session** - View detailed info (task, runtime, PID, IDE)
- **Refresh** - Manually refresh the session list
- **Open Logs** - Open the logs folder in Finder
- **Stats** - View statistics (active, completed today, averages)

### Enhanced Tracking (Optional)

For even better metadata, use the `claude-tracked` wrapper:

```bash
# Make it executable
chmod +x claude-tracked

# Use it instead of claude-code
./claude-tracked "add unit tests for user service"

# Or create an alias
echo 'alias cc="~/path/to/claude-tracked"' >> ~/.zshrc
source ~/.zshrc

# Then just use:
cc "your task here"
```

## What Gets Tracked

For each session:
- **Task description** - The command/task you gave Claude
- **IDE/Terminal** - Where the session was launched from
- **Start time** - When the session started
- **Runtime** - How long it's been running
- **Status** - Running or completed
- **Process ID** - For process management

## Data Storage

All data is stored locally in `~/.claude-tracker/`:
- `sessions.json` - Session history
- `logs/` - Session logs (if using wrapper)
- `metadata/` - Enhanced metadata (if using wrapper)

## Notifications

You'll receive notifications for:
- 🚀 New session detected
- ✅ Session completed

## Statistics

Track your productivity:
- Active sessions count (shown in menu bar)
- Sessions completed today
- Average session duration
- Total sessions tracked

## Tips

### Multiple IDEs
The tracker works seamlessly when you have:
- RubyMine with one session
- VS Code with another
- Terminal with a third

All will be tracked independently!

### Shell Aliases

Add to your `~/.zshrc` or `~/.bashrc`:

```bash
# Quick access
alias ct='~/path/to/claude-tracker.py'

# Enhanced tracking
alias cc='~/path/to/claude-tracked'

# Or override claude-code entirely
alias claude-code='~/path/to/claude-tracked'
```

### Auto-start on Login

The installer offers to set this up, but you can also do it manually:

```bash
# The plist file is created at:
~/Library/LaunchAgents/com.claude-tracker.plist

# To load it:
launchctl load ~/Library/LaunchAgents/com.claude-tracker.plist

# To unload it:
launchctl unload ~/Library/LaunchAgents/com.claude-tracker.plist
```

## Troubleshooting

### Icon not appearing
- Make sure Python 3 is installed: `python3 --version`
- Check if the app is running: `ps aux | grep claude-tracker`
- Try running with: `python3 claude-tracker.py`

### Sessions not detected
- Verify `claude-code` is in your PATH: `which claude-code`
- Check if processes are visible: `ps aux | grep claude-code`
- Try refreshing from the menu bar

### Permissions issues
- The app needs permission to access running processes
- Grant terminal/IDE permissions in System Preferences > Security & Privacy

## Uninstallation

```bash
# Stop auto-start
launchctl unload ~/Library/LaunchAgents/com.claude-tracker.plist
rm ~/Library/LaunchAgents/com.claude-tracker.plist

# Remove data
rm -rf ~/.claude-tracker

# Uninstall Python packages (optional)
pip3 uninstall rumps psutil
```

## Advanced

### Custom Notifications

Edit `claude-tracker.py` and modify the `notify()` method to customize notification behavior.

### Logging

To add custom logging, modify the `scan_processes()` method to write to log files.

### API Integration

The session data is stored in JSON format at `~/.claude-tracker/sessions.json`, making it easy to integrate with other tools.

## Support

If you encounter issues:
1. Check that Python 3.7+ is installed
2. Verify `rumps` and `psutil` are installed
3. Make sure you have the necessary permissions
4. Check Console.app for any error messages

## License

Free to use and modify!

---

Built for developers managing multiple AI agent sessions 🚀
