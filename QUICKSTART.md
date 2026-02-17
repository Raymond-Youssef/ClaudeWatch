# Quick Start Guide 🚀

## Get Running in 60 Seconds

### Step 1: Install
```bash
./install.sh
```

### Step 2: Start the Tracker
```bash
./claude-tracker.py
```

You'll see 🤖 in your menu bar!

### Step 3: Use Claude Code Normally
```bash
# In RubyMine terminal
claude-code "refactor authentication"

# In another terminal
claude-code "add tests"

# In VS Code
claude-code "fix bug in user service"
```

All sessions are automatically tracked! 🎉

### Step 4: Check Your Sessions
Click the 🤖 icon in your menu bar to see:
- All active sessions
- Which IDE each is running in  
- How long each has been running
- Get notified when they complete

## That's It!

The tracker runs silently in the background and automatically detects all your Claude Code sessions across:
- ✅ RubyMine
- ✅ VS Code  
- ✅ PyCharm
- ✅ Terminal
- ✅ iTerm
- ✅ Any other IDE or terminal

## Bonus: Enhanced Tracking

For even better metadata:
```bash
# Use the wrapper instead
./claude-tracked "your task"

# Or create an alias
echo 'alias cc="$HOME/path/to/claude-tracked"' >> ~/.zshrc
source ~/.zshrc

cc "your task here"
```

## Auto-Start on Login

The installer asks if you want this. If you said yes, the tracker will automatically start when you log in!

If you skipped it, run the installer again or manually set it up (see README.md).

---

**Need help?** Check README.md for full documentation.
