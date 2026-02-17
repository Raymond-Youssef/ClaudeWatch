"""ClaudeWatch(rumps.App) — menu bar UI that wires together all modules."""

import os
import time
from pathlib import Path

import rumps

from claudewatch.focus import FocusManager
from claudewatch.jsonl import JsonlParser
from claudewatch.monitor import ProcessMonitor
from claudewatch.notifications import Notifier
from claudewatch.session import SessionManager

APP_NAME = 'ClaudeWatch'


class ClaudeWatch(rumps.App):
    def __init__(self):
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'icon.png')
        super(ClaudeWatch, self).__init__("ClaudeWatch", icon=icon_path, quit_button=None)

        self.session_mgr = SessionManager()
        self.notifier = Notifier()
        self.focus_mgr = FocusManager()
        self.monitor = ProcessMonitor(on_scan=self._on_monitor_scan)

        self.dynamic_menu_keys = []

        self.menu = [
            rumps.MenuItem('Active Sessions', callback=None),
            rumps.separator,
            rumps.MenuItem('Refresh', callback=self.refresh_sessions),
            rumps.separator,
            rumps.MenuItem('Stats', callback=self.show_stats),
            rumps.separator,
            rumps.MenuItem('Quit', callback=self.quit_app),
        ]

        @rumps.notifications
        def _on_notification(info):
            self._handle_notification(info)

        self.monitor.start()
        self.update_menu()

    def _on_monitor_scan(self):
        """Callback invoked by ProcessMonitor on each scan cycle."""
        active_procs = self.monitor.scan_processes()
        active_pids = set(active_procs.keys())

        # Detect new sessions
        for pid, meta in active_procs.items():
            if pid not in self.session_mgr.sessions:
                cwd = meta['cwd'] or ''
                jsonl_path = JsonlParser.find_session_jsonl(cwd, meta['create_time']) if cwd else None
                title = JsonlParser.get_conversation_title(jsonl_path)
                self.session_mgr.add_session(
                    pid=pid,
                    title=title,
                    create_time=meta['create_time'],
                    ide=meta['ide'],
                    cwd=cwd,
                    jsonl_path=jsonl_path,
                    tty=meta['tty'],
                )
                self.update_menu()
                self.notifier.notify(f"New session in {meta['ide']}", (title or 'New conversation')[:100], pid)

        # Check state transitions for running sessions
        for pid, session in list(self.session_mgr.sessions.items()):
            if session['status'] != 'running' or pid not in active_pids:
                continue
            jsonl_str = session.get('jsonl', '')
            state = JsonlParser.get_session_state(jsonl_str)
            prev_state = session.get('last_state', 'active')

            if state != prev_state and state in ('waiting_tool', 'waiting_input'):
                title = session.get('title', 'Unknown')[:100]
                if state == 'waiting_tool':
                    self.notifier.notify(f"Needs approval in {session['ide']}", title, pid)
                else:
                    self.notifier.notify(f"Waiting for input in {session['ide']}", title, pid)

            self.session_mgr.update_state(pid, state)

        # Detect completed sessions
        for pid, session in list(self.session_mgr.sessions.items()):
            if session['status'] == 'running' and pid not in active_pids:
                if not session.get('notified', False):
                    self.notifier.notify("Session completed", session.get('title', 'Unknown')[:100], pid)
                self.session_mgr.complete_session(pid)
                self.update_menu()

    def _handle_notification(self, info):
        """Handle notification click — focus the IDE window for the session."""
        pid = info.get('pid') if info else None
        if pid:
            session = self.session_mgr.sessions.get(str(pid))
            if session:
                self.focus_mgr.focus_session(session)

    def update_menu(self):
        """Update the menu bar with current sessions."""
        for key in self.dynamic_menu_keys:
            try:
                del self.menu[key]
            except KeyError:
                pass
        self.dynamic_menu_keys = []

        active = self.session_mgr.get_active()

        if active:
            self.title = f" {len(active)}"
        else:
            self.title = ""

        items_to_add = []
        if active:
            for session in sorted(active, key=lambda x: x['started_at'], reverse=True):
                runtime = self._format_duration(time.time() - session['started_at'])
                title = session.get('title', 'New conversation')
                if len(title) > 40:
                    title = title[:40] + '...'
                ide = session.get('ide', 'Terminal')

                title_label = f"{ide} - {title}  ({runtime})"
                title_item = rumps.MenuItem(title_label, callback=lambda sender, s=session: self.focus_mgr.focus_session(s))
                items_to_add.append((title_label, title_item))

                jsonl_str = session.get('jsonl', '')
                jsonl_path = Path(jsonl_str) if jsonl_str else None
                latest = JsonlParser.get_latest_response(jsonl_path) if jsonl_path else None
                msg_text = latest.replace('\n', ' ')[:70] if latest else 'Waiting for response...'
                msg_key = f"  {msg_text}"
                msg_item = rumps.MenuItem(msg_key, callback=None)
                items_to_add.append((msg_key, msg_item))
        else:
            items_to_add.append(('No active sessions', rumps.MenuItem('No active sessions', callback=None)))

        for key, item in reversed(items_to_add):
            self.menu.insert_after('Active Sessions', item)
            self.dynamic_menu_keys.append(key)

    def refresh_sessions(self, _):
        """Manually refresh sessions."""
        self._on_monitor_scan()
        self.update_menu()
        rumps.notification(APP_NAME, 'Refreshed', 'Session list updated')

    def show_stats(self, _):
        """Show statistics."""
        stats = self.session_mgr.get_stats()
        msg = f"Active sessions: {stats['active']}\n"
        msg += f"Completed today: {stats['completed_today']}\n"
        msg += f"Total tracked: {stats['total']}\n\n"
        if stats['avg_duration']:
            msg += f"Avg session time today: {self._format_duration(stats['avg_duration'])}"
        rumps.alert(APP_NAME, msg)

    def quit_app(self, _):
        """Quit the application."""
        self.monitor.stop()
        rumps.quit_application()

    @staticmethod
    def _format_duration(seconds):
        """Format duration in human readable form."""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds / 60)}m"
        else:
            return f"{int(seconds / 3600)}h {int((seconds % 3600) / 60)}m"
