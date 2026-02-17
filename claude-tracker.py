#!/usr/bin/env python3
"""
ClaudeBoard - macOS Menu Bar App
Tracks all running Claude Code sessions across different IDEs and terminals.
"""

import rumps
import psutil
import json
import os
import re
from datetime import datetime
from pathlib import Path
import subprocess
import threading
import time

APP_NAME = 'ClaudeBoard'

class ClaudeBoard(rumps.App):
    def __init__(self):
        super(ClaudeBoard, self).__init__("🤖", quit_button=None)

        # Setup data directory
        self.data_dir = Path.home() / '.claudeboard'
        self.data_dir.mkdir(exist_ok=True)
        self.sessions_file = self.data_dir / 'sessions.json'

        # Load existing sessions
        self.sessions = self.load_sessions()

        # Track dynamic menu item keys so we can remove them later
        self.dynamic_menu_keys = []

        # Setup menu
        self.menu = [
            rumps.MenuItem('Active Sessions', callback=None),
            rumps.separator,
            rumps.MenuItem('Refresh', callback=self.refresh_sessions),
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
            except Exception:
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
            time.sleep(2)

    def is_claude_code_process(self, proc_info):
        """Check if a process is a Claude Code CLI session"""
        cmdline = proc_info['cmdline'] or []
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

    def is_waiting_for_input(self, jsonl_str):
        """Check if a session is idle and waiting for user input"""
        try:
            if not jsonl_str:
                return False
            jsonl_path = Path(jsonl_str)
            if not jsonl_path.exists():
                return False
            age = time.time() - jsonl_path.stat().st_mtime
            if age < 10:
                return False
            return True
        except Exception:
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
                        create_time = proc.info['create_time']
                        jsonl_path = self.find_session_jsonl(cwd, create_time) if cwd else None
                        title = self.get_conversation_title(jsonl_path)
                        ide = self.detect_parent_ide(proc)
                        tty = None
                        try:
                            tty = psutil.Process(int(pid)).terminal()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                        self.sessions[pid] = {
                            'pid': pid,
                            'title': title or 'New conversation',
                            'started_at': create_time,
                            'status': 'running',
                            'ide': ide,
                            'cwd': cwd,
                            'jsonl': str(jsonl_path) if jsonl_path else '',
                            'tty': tty,
                            'notified': False,
                            'input_notified': False
                        }
                        self.save_sessions()
                        self.update_menu()
                        self.notify(f"New session in {ide}", (title or 'New conversation')[:100], pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Check for sessions waiting for input
        for pid, session in list(self.sessions.items()):
            if session['status'] != 'running' or pid not in active_pids:
                continue
            jsonl_str = session.get('jsonl', '')
            waiting = self.is_waiting_for_input(jsonl_str)
            if waiting and not session.get('input_notified', False):
                session['input_notified'] = True
                self.notify(
                    f"Waiting for input in {session['ide']}",
                    session.get('title', 'Unknown')[:100],
                    pid
                )
                self.save_sessions()
            elif not waiting and session.get('input_notified', False):
                # User resumed — reset so we can notify again next time
                session['input_notified'] = False
                self.save_sessions()

        # Check for completed sessions
        for pid, session in list(self.sessions.items()):
            if session['status'] == 'running' and pid not in active_pids:
                session['status'] = 'completed'
                session['ended_at'] = time.time()

                if not session.get('notified', False):
                    self.notify("Session completed", session.get('title', 'Unknown')[:100], pid)
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

    def get_project_dir(self, cwd):
        """Convert a cwd to the Claude projects directory path"""
        project_dir_name = re.sub(r'[^a-zA-Z0-9]', '-', cwd)
        return Path.home() / '.claude' / 'projects' / project_dir_name

    def find_session_jsonl(self, cwd, process_create_time):
        """Find the JSONL file for a specific session by matching process creation time."""
        try:
            projects_base = self.get_project_dir(cwd)
            if not projects_base.is_dir():
                return None
            jsonl_files = list(projects_base.glob('*.jsonl'))
            if not jsonl_files:
                return None
            if len(jsonl_files) == 1:
                return jsonl_files[0]

            # Read history.jsonl to map session UUIDs to start timestamps
            history_path = Path.home() / '.claude' / 'history.jsonl'
            if not history_path.exists():
                return max(jsonl_files, key=lambda f: f.stat().st_mtime)

            session_first_ts = {}
            with open(history_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    sid = obj.get('sessionId', '')
                    ts = int(obj.get('timestamp', 0)) / 1000
                    if sid and ts and sid not in session_first_ts:
                        session_first_ts[sid] = ts

            jsonl_by_uuid = {f.stem: f for f in jsonl_files}
            best_match = None
            best_diff = float('inf')
            for uuid, path in jsonl_by_uuid.items():
                ts = session_first_ts.get(uuid)
                if ts is None:
                    continue
                diff = ts - process_create_time
                if 0 <= diff < 30 and diff < best_diff:
                    best_diff = diff
                    best_match = path

            return best_match or max(jsonl_files, key=lambda f: f.stat().st_mtime)
        except Exception:
            return None

    def get_conversation_title(self, jsonl_path):
        """Get the conversation title (first user text message) from the JSONL"""
        try:
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

    def get_latest_response(self, jsonl_path):
        """Get the latest assistant text response from the JSONL"""
        try:
            if not jsonl_path:
                return None
            with open(jsonl_path, 'rb') as f:
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
        for key in self.dynamic_menu_keys:
            try:
                del self.menu[key]
            except KeyError:
                pass
        self.dynamic_menu_keys = []

        active = [s for s in self.sessions.values() if s['status'] == 'running']

        if active:
            self.title = f"🤖 {len(active)}"
        else:
            self.title = "🤖"

        items_to_add = []
        if active:
            for session in sorted(active, key=lambda x: x['started_at'], reverse=True):
                runtime = self.format_duration(time.time() - session['started_at'])
                title = session.get('title', 'New conversation')
                if len(title) > 40:
                    title = title[:40] + '...'
                ide = session.get('ide', 'Terminal')

                # Title line: primary/white (clickable, focuses IDE)
                title_label = f"{ide} - {title}  ({runtime})"
                title_item = rumps.MenuItem(title_label, callback=lambda sender, s=session: self.show_session(s))
                items_to_add.append((title_label, title_item))

                # Last message: secondary (grayed out)
                jsonl_str = session.get('jsonl', '')
                jsonl_path = Path(jsonl_str) if jsonl_str else None
                latest = self.get_latest_response(jsonl_path) if jsonl_path else None
                msg_text = latest.replace('\n', ' ')[:70] if latest else 'Waiting for response...'
                msg_key = f"  {msg_text}"
                msg_item = rumps.MenuItem(msg_key, callback=None)
                items_to_add.append((msg_key, msg_item))
        else:
            items_to_add.append(('No active sessions', rumps.MenuItem('No active sessions', callback=None)))

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
        rumps.notification(APP_NAME, 'Refreshed', 'Session list updated')

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

        rumps.alert(APP_NAME, msg)

    def notify(self, title, message, pid=None):
        """Send macOS notification with session PID as data"""
        rumps.notification(APP_NAME, title, message, data={'pid': pid} if pid else None)

    def handle_notification(self, info):
        """Handle notification click — focus the IDE window for the session"""
        pid = info.get('pid') if info else None
        if pid:
            session = self.sessions.get(str(pid))
            if session:
                self.focus_ide(session)

    def focus_ide(self, session):
        """Bring the IDE/terminal window for a session to the foreground, focusing the exact tab if possible"""
        ide = session.get('ide', '')
        tty = session.get('tty', '')

        app_name_map = {
            'VS Code': 'Visual Studio Code',
            'RubyMine': 'RubyMine',
            'PyCharm': 'PyCharm',
            'IntelliJ': 'IntelliJ IDEA',
            'WebStorm': 'WebStorm',
            'GoLand': 'GoLand',
            'Cursor': 'Cursor',
            'iTerm': 'iTerm2',
            'Terminal': 'Terminal',
            'Warp': 'Warp',
            'Alacritty': 'Alacritty',
            'Kitty': 'kitty',
        }
        app_name = app_name_map.get(ide, ide)

        # For Terminal.app: select exact tab by TTY
        if ide == 'Terminal' and tty:
            try:
                subprocess.run(['osascript', '-e', f'''
                    tell application "Terminal"
                        activate
                        repeat with w in windows
                            repeat with t in tabs of w
                                if tty of t is "{tty}" then
                                    set selected of t to true
                                    set index of w to 1
                                    return
                                end if
                            end repeat
                        end repeat
                    end tell
                '''], timeout=3)
                return
            except Exception:
                pass

        # For iTerm2: select exact session by TTY
        if ide == 'iTerm' and tty:
            try:
                subprocess.run(['osascript', '-e', f'''
                    tell application "iTerm2"
                        activate
                        repeat with w in windows
                            repeat with t in tabs of w
                                repeat with s in sessions of t
                                    if tty of s is "{tty}" then
                                        select t
                                        select s
                                        set index of w to 1
                                        return
                                    end if
                                end repeat
                            end repeat
                        end repeat
                    end tell
                '''], timeout=3)
                return
            except Exception:
                pass

        # Fallback: activate the application
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
    ClaudeBoard().run()
