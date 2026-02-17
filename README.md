# ClaudeWatch 🤖

A lightweight macOS menu bar app that tracks all your Claude Code sessions across different IDEs and terminals.

## Features

✨ **System-wide tracking** - Monitors all `claude` processes regardless of where they're launched
🔔 **Desktop notifications** - Get notified when sessions start, complete, or are waiting for input
📊 **Live dashboard** - Click the menu bar icon to see all active sessions with latest responses
⏱️ **Runtime tracking** - See how long each session has been running
🎯 **IDE detection** - Automatically detects which IDE/terminal launched each session
🔀 **Click to focus** - Click a session to switch to the correct IDE/terminal window and tab
📈 **Statistics** - Track completed sessions and average runtime
🪶 **Lightweight** - Minimal resource usage, runs silently in the background

## Installation

### Prerequisites
- macOS 10.14 (Mojave) or later
- Python 3.7+
- Claude Code installed

### Quick Install

```bash
# Clone or download these files to a folder
cd ClaudeWatch

# Run the installer
chmod +x install.sh
./install.sh
```

The installer will:
1. Install required Python packages (`rumps`, `psutil`)
2. Make the app executable
3. Optionally configure auto-start on login

### Manual Installation

```bash
pip3 install -r requirements.txt
chmod +x claudewatch.py
./claudewatch.py
```

## Usage

### Starting ClaudeWatch

```bash
./claudewatch.py
```

You'll see a 🤖 icon appear in your menu bar.

### Using Claude Code Normally

Just use `claude` as you normally would - from any IDE or terminal:

```bash
claude "refactor the authentication module"
```

ClaudeWatch will automatically detect and track the session!

### Menu Bar Features

Click the 🤖 icon to:
- **View active sessions** - See all running sessions with runtime, IDE, and latest response
- **Click a session** - Focus the IDE/terminal window (and exact tab) where the session is running
- **Refresh** - Manually refresh the session list
- **Stats** - View statistics (active, completed today, averages)

## What Gets Tracked

For each session:
- **Conversation title** - The first user message from the session
- **Latest response** - The most recent assistant message, shown in the menu
- **IDE/Terminal** - Where the session was launched from (VS Code, Cursor, RubyMine, PyCharm, IntelliJ, WebStorm, GoLand, iTerm, Terminal, Warp, Alacritty, Kitty)
- **Start time** - When the session started
- **Runtime** - How long it's been running
- **Status** - Running or completed

## Data Storage

All data is stored locally in `~/.claudewatch/`:
- `sessions.json` - Session history

## Notifications

You'll receive notifications for:
- 🚀 New session detected
- ⏳ Session waiting for input (Claude finished and is waiting for you)
- ✅ Session completed

Clicking a notification will focus the IDE/terminal window for that session.

## Statistics

Track your productivity:
- Active sessions count (shown in menu bar as 🤖 N)
- Sessions completed today
- Average session duration
- Total sessions tracked

## Tips

### Multiple IDEs
ClaudeWatch works seamlessly when you have:
- RubyMine with one session
- VS Code with another
- Terminal with a third

All will be tracked independently!

### Shell Aliases

Add to your `~/.zshrc` or `~/.bashrc`:

```bash
# Quick access to start ClaudeWatch
alias cw='~/path/to/claudewatch.py'
```

### Auto-start on Login

The installer offers to set this up, but you can also do it manually:

```bash
# The plist file is created at:
~/Library/LaunchAgents/com.claudewatch.plist

# To load it:
launchctl load ~/Library/LaunchAgents/com.claudewatch.plist

# To unload it:
launchctl unload ~/Library/LaunchAgents/com.claudewatch.plist
```

## Troubleshooting

### Icon not appearing
- Make sure Python 3 is installed: `python3 --version`
- Check if the app is running: `ps aux | grep claudewatch`
- Try running with: `python3 claudewatch.py`

### Sessions not detected
- Verify `claude` is in your PATH: `which claude`
- Check if processes are visible: `ps aux | grep claude`
- Try refreshing from the menu bar

### Permissions issues
- The app needs permission to access running processes
- Grant terminal/IDE permissions in System Preferences > Security & Privacy

## Uninstallation

Run the uninstall script:

```bash
./uninstall.sh
```

Or manually:

```bash
# Stop auto-start
launchctl unload ~/Library/LaunchAgents/com.claudewatch.plist
rm ~/Library/LaunchAgents/com.claudewatch.plist

# Remove data
rm -rf ~/.claudewatch

# Uninstall Python packages (optional)
pip3 uninstall rumps psutil
```

## Advanced

### Custom Notifications

Edit `claudewatch.py` and modify the `notify()` method to customize notification behavior.

### API Integration

The session data is stored in JSON format at `~/.claudewatch/sessions.json`, making it easy to integrate with other tools.

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
