#!/usr/bin/env python3
"""
Claude Code Session Tracker - macOS Menu Bar App
Tracks all running Claude Code sessions across different IDEs and terminals.
"""

import rumps
import psutil
import json
import os
from datetime import datetime
from pathlib import Path
import subprocess
import threading
import time

class ClaudeTracker(rumps.App):
    def __init__(self):
        super(ClaudeTracker, self).__init__("🤖", quit_button=None)
        
        # Setup data directory
        self.data_dir = Path.home() / '.claude-tracker'
        self.data_dir.mkdir(exist_ok=True)
        self.sessions_file = self.data_dir / 'sessions.json'
        self.logs_dir = self.data_dir / 'logs'
        self.logs_dir.mkdir(exist_ok=True)
        
        # Load existing sessions
        self.sessions = self.load_sessions()
        
        # Track dynamic menu item keys so we can remove them later
        self.dynamic_menu_keys = []

        # Setup menu
        self.menu = [
            rumps.MenuItem('Active Sessions', callback=None),
            rumps.separator,
            rumps.MenuItem('Refresh', callback=self.refresh_sessions),
            rumps.MenuItem('Open Logs Folder', callback=self.open_logs),
            rumps.separator,
            rumps.MenuItem('Stats', callback=self.show_stats),
            rumps.separator,
            rumps.MenuItem('Quit', callback=self.quit_app)
        ]

        # Start monitoring thread
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self.monitor_processes, daemon=True)
        self.monitor_thread.start()
        
        # Update menu
        self.update_menu()
    
    def load_sessions(self):
        """Load sessions from disk"""
        if self.sessions_file.exists():
            try:
                with open(self.sessions_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def save_sessions(self):
        """Save sessions to disk"""
        with open(self.sessions_file, 'w') as f:
            json.dump(self.sessions, f, indent=2)
    
    def monitor_processes(self):
        """Background thread to monitor claude-code processes"""
        while self.monitoring:
            self.scan_processes()
            time.sleep(2)  # Check every 2 seconds
    
    def is_claude_code_process(self, proc_info):
        """Check if a process is a Claude Code CLI session"""
        cmdline = proc_info['cmdline'] or []
        name = proc_info['name'] or ''
        cmdline_str = ' '.join(cmdline)

        # Skip Claude desktop app and its helpers
        if '/Applications/Claude.app' in cmdline_str or 'chrome-native-host' in cmdline_str:
            return False

        # Match: cmdline contains 'claude' or 'claude-code' as a command
        for arg in cmdline:
            basename = os.path.basename(arg)
            if basename in ('claude', 'claude-code'):
                return True

        return False

    def scan_processes(self):
        """Scan for running claude-code processes"""
        active_pids = set()

        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
            try:
                cmdline = proc.info['cmdline']
                if cmdline and self.is_claude_code_process(proc.info):
                    pid = str(proc.info['pid'])
                    active_pids.add(pid)

                    if pid not in self.sessions:
                        # New session detected
                        task = ' '.join(cmdline[1:]) if len(cmdline) > 1 else 'Interactive session'
                        self.sessions[pid] = {
                            'pid': pid,
                            'task': task,
                            'started_at': proc.info['create_time'],
                            'status': 'running',
                            'ide': self.detect_parent_ide(proc),
                            'notified': False
                        }
                        self.save_sessions()
                        self.update_menu()
                        self.notify(f"New session started", task[:100])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Check for completed sessions
        for pid, session in list(self.sessions.items()):
            if session['status'] == 'running' and pid not in active_pids:
                # Session completed
                session['status'] = 'completed'
                session['ended_at'] = time.time()
                
                if not session.get('notified', False):
                    self.notify("Session completed ✓", session['task'][:100])
                    session['notified'] = True
                
                self.save_sessions()
                self.update_menu()
    
    def detect_parent_ide(self, proc):
        """Try to detect which IDE/terminal launched this process"""
        try:
            parent = proc.parent()
            if parent:
                parent_name = parent.name().lower()
                if 'rubymine' in parent_name:
                    return 'RubyMine'
                elif 'code' in parent_name or 'vscode' in parent_name:
                    return 'VS Code'
                elif 'terminal' in parent_name or 'iterm' in parent_name:
                    return parent.name()
                elif 'pycharm' in parent_name:
                    return 'PyCharm'
                elif 'intellij' in parent_name:
                    return 'IntelliJ'
                return parent.name()
        except:
            pass
        return 'Unknown'
    
    def update_menu(self):
        """Update the menu bar with current sessions"""
        # Remove previously added dynamic items
        for key in self.dynamic_menu_keys:
            try:
                del self.menu[key]
            except KeyError:
                pass
        self.dynamic_menu_keys = []

        # Get active sessions
        active = [s for s in self.sessions.values() if s['status'] == 'running']

        # Update title with count
        if active:
            self.title = f"🤖 {len(active)}"
        else:
            self.title = "🤖"

        # Build dynamic items to insert after "Active Sessions" header
        items_to_add = []
        if active:
            for session in sorted(active, key=lambda x: x['started_at'], reverse=True):
                runtime = self.format_duration(time.time() - session['started_at'])
                label = f"⚡ {session['task'][:50]}... ({runtime}) [{session['ide']}]"
                item = rumps.MenuItem(label, callback=lambda sender, s=session: self.show_session(s))
                items_to_add.append((label, item))
        else:
            items_to_add.append(('No active sessions', rumps.MenuItem('No active sessions', callback=None)))

        # Insert items right after the "Active Sessions" header
        for key, item in reversed(items_to_add):
            self.menu.insert_after('Active Sessions', item)
            self.dynamic_menu_keys.append(key)
    
    def format_duration(self, seconds):
        """Format duration in human readable form"""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds/60)}m"
        else:
            return f"{int(seconds/3600)}h {int((seconds%3600)/60)}m"
    
    def show_session(self, session):
        """Show session details"""
        runtime = self.format_duration(time.time() - session['started_at'])
        msg = f"Task: {session['task']}\n\n"
        msg += f"IDE: {session['ide']}\n"
        msg += f"Runtime: {runtime}\n"
        msg += f"PID: {session['pid']}\n"
        msg += f"Started: {datetime.fromtimestamp(session['started_at']).strftime('%H:%M:%S')}"
        
        rumps.alert('Session Details', msg)
    
    def refresh_sessions(self, _):
        """Manually refresh sessions"""
        self.scan_processes()
        self.update_menu()
        rumps.notification('Claude Tracker', 'Refreshed', 'Session list updated')
    
    def open_logs(self, _):
        """Open logs folder in Finder"""
        subprocess.run(['open', str(self.logs_dir)])
    
    def show_stats(self, _):
        """Show statistics"""
        active = [s for s in self.sessions.values() if s['status'] == 'running']
        completed_today = [s for s in self.sessions.values() 
                          if s['status'] == 'completed' 
                          and s.get('ended_at', 0) > time.time() - 86400]
        total = len(self.sessions)
        
        msg = f"Active sessions: {len(active)}\n"
        msg += f"Completed today: {len(completed_today)}\n"
        msg += f"Total tracked: {total}\n\n"
        
        if completed_today:
            avg_duration = sum(s.get('ended_at', 0) - s['started_at'] 
                             for s in completed_today) / len(completed_today)
            msg += f"Avg session time today: {self.format_duration(avg_duration)}"
        
        rumps.alert('Stats', msg)
    
    def notify(self, title, message):
        """Send macOS notification"""
        rumps.notification('Claude Tracker', title, message)
    
    def quit_app(self, _):
        """Quit the application"""
        self.monitoring = False
        rumps.quit_application()

if __name__ == '__main__':
    ClaudeTracker().run()
