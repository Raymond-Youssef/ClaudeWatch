#!/usr/bin/env python3
"""
Claude Code Session Tracker - macOS Menu Bar App
Tracks all running Claude Code sessions across different IDEs and terminals.
"""

import rumps
import psutil
import json
import os
import glob as globmod
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

        # Register notification click handler
        @rumps.notifications
        def _on_notification(info):
            self.handle_notification(info)

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
                        cwd = self.get_session_cwd(pid) or ''
                        title = self.get_conversation_title(cwd) if cwd else None
                        ide = self.detect_parent_ide(proc)
                        self.sessions[pid] = {
                            'pid': pid,
                            'title': title or 'New conversation',
                            'started_at': proc.info['create_time'],
                            'status': 'running',
                            'ide': ide,
                            'cwd': cwd,
                            'notified': False
                        }
                        self.save_sessions()
                        self.update_menu()
                        self.notify(f"New session in {ide}", (title or 'New conversation')[:100], pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Check for completed sessions
        for pid, session in list(self.sessions.items()):
            if session['status'] == 'running' and pid not in active_pids:
                # Session completed
                session['status'] = 'completed'
                session['ended_at'] = time.time()
                
                if not session.get('notified', False):
                    self.notify("Session completed ✓", session.get('title', 'Unknown')[:100], pid)
                    session['notified'] = True
                
                self.save_sessions()
                self.update_menu()
    
    def detect_parent_ide(self, proc):
        """Walk the ancestor process chain to detect the IDE/terminal"""
        ide_patterns = {
            'rubymine': 'RubyMine',
            'code helper': 'VS Code',
            'vscode': 'VS Code',
            'electron': 'VS Code',
            'pycharm': 'PyCharm',
            'intellij': 'IntelliJ',
            'webstorm': 'WebStorm',
            'goland': 'GoLand',
            'cursor': 'Cursor',
            'iterm': 'iTerm',
            'terminal': 'Terminal',
            'warp': 'Warp',
            'alacritty': 'Alacritty',
            'kitty': 'Kitty',
        }
        try:
            ancestor = proc.parent()
            while ancestor and ancestor.pid > 1:
                name = ancestor.name().lower()
                for pattern, label in ide_patterns.items():
                    if pattern in name:
                        return label
                ancestor = ancestor.parent()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return 'Terminal'

    def get_session_cwd(self, pid):
        """Get the working directory of a process"""
        try:
            return psutil.Process(int(pid)).cwd()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def get_session_jsonl(self, cwd):
        """Find the most recently modified JSONL conversation file for a project cwd"""
        try:
            import re
            project_dir_name = re.sub(r'[^a-zA-Z0-9]', '-', cwd)
            projects_base = Path.home() / '.claude' / 'projects' / project_dir_name
            if not projects_base.is_dir():
                return None
            jsonl_files = list(projects_base.glob('*.jsonl'))
            if not jsonl_files:
                return None
            return max(jsonl_files, key=lambda f: f.stat().st_mtime)
        except Exception:
            return None

    def get_conversation_title(self, cwd):
        """Get the conversation title (first user text message) from the JSONL"""
        try:
            jsonl_path = self.get_session_jsonl(cwd)
            if not jsonl_path:
                return None
            with open(jsonl_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    msg = obj.get('message', {})
                    if msg.get('role') == 'user':
                        content = msg.get('content', '')
                        if isinstance(content, str) and content.strip():
                            return content.strip()
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get('type') == 'text' and block.get('text', '').strip():
                                    return block['text'].strip()
        except Exception:
            pass
        return None

    def get_latest_response(self, cwd):
        """Get the latest assistant text response from the JSONL"""
        try:
            jsonl_path = self.get_session_jsonl(cwd)
            if not jsonl_path:
                return None
            with open(jsonl_path, 'rb') as f:
                # Read last 50KB to avoid loading huge files
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 50000))
                tail = f.read().decode('utf-8', errors='replace')
            for line in reversed(tail.splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = obj.get('message', {})
                if msg.get('role') == 'assistant':
                    for block in msg.get('content', []):
                        if block.get('type') == 'text' and block.get('text', '').strip():
                            return block['text'].strip()
        except Exception:
            pass
        return None
    
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
                title = session.get('title', 'New conversation')
                if len(title) > 40:
                    title = title[:40] + '...'
                ide = session.get('ide', 'Terminal')

                # Title line: secondary (grayed out, no callback)
                title_label = f"{ide} - {title}  ({runtime})"
                title_item = rumps.MenuItem(title_label, callback=None)
                items_to_add.append((title_label, title_item))

                # Last message: primary/white (clickable, focuses IDE)
                cwd = session.get('cwd', '')
                latest = self.get_latest_response(cwd) if cwd else None
                msg_text = latest.replace('\n', ' ')[:70] if latest else 'Waiting for response...'
                msg_key = f"  {msg_text}"
                msg_item = rumps.MenuItem(msg_key, callback=lambda sender, s=session: self.show_session(s))
                items_to_add.append((msg_key, msg_item))
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
        """Click a session to focus its IDE/terminal window"""
        self.focus_ide(session)
    
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
    
    def notify(self, title, message, pid=None):
        """Send macOS notification with session PID as data"""
        rumps.notification('Claude Tracker', title, message, data={'pid': pid} if pid else None)

    def handle_notification(self, info):
        """Handle notification click — focus the IDE window for the session"""
        pid = info.get('pid') if info else None
        if pid:
            session = self.sessions.get(str(pid))
            if session:
                self.focus_ide(session)

    def focus_ide(self, session):
        """Bring the IDE/terminal window for a session to the foreground"""
        ide = session.get('ide', '')
        # Map our IDE labels to macOS application names
        app_name_map = {
            'VS Code': 'Visual Studio Code',
            'RubyMine': 'RubyMine',
            'PyCharm': 'PyCharm',
            'IntelliJ': 'IntelliJ IDEA',
            'WebStorm': 'WebStorm',
            'GoLand': 'GoLand',
            'Cursor': 'Cursor',
            'iTerm': 'iTerm',
            'Terminal': 'Terminal',
            'Warp': 'Warp',
            'Alacritty': 'Alacritty',
            'Kitty': 'kitty',
        }
        app_name = app_name_map.get(ide, ide)
        if app_name:
            try:
                subprocess.run([
                    'osascript', '-e',
                    f'tell application "{app_name}" to activate'
                ], timeout=3)
            except Exception:
                pass

    def quit_app(self, _):
        """Quit the application"""
        self.monitoring = False
        rumps.quit_application()

if __name__ == '__main__':
    ClaudeTracker().run()
