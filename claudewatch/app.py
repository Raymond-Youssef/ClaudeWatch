"""ClaudeWatch(rumps.App) — event-driven menu bar UI for Claude Code sessions."""

import os
import sys
import time
from pathlib import Path

import rumps
from PyObjCTools.AppHelper import callAfter

from claudewatch.focus import FocusManager
from claudewatch.jsonl import JsonlParser
from claudewatch.monitor import ProcessMonitor
from claudewatch.notifications import Notifier
from claudewatch.pidwatcher import PidWatcher
from claudewatch.session import SessionManager
from claudewatch.watcher import JsonlWatcher

APP_NAME = 'ClaudeWatch'
DISCOVERY_INTERVAL = 12  # seconds between process scans


class ClaudeWatch(rumps.App):
    def __init__(self):
        if getattr(sys, 'frozen', False):
            icon_path = os.path.join(os.environ.get('RESOURCEPATH', ''), 'icon.png')
        else:
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'icon.png')
        super(ClaudeWatch, self).__init__("ClaudeWatch", icon=icon_path, quit_button=None)

        self.session_mgr = SessionManager()
        self.session_mgr.prune_old_sessions()

        self.notifier = Notifier()
        self.focus_mgr = FocusManager()
        self.monitor = ProcessMonitor()

        # Event-driven subsystems
        self.pid_watcher = PidWatcher(on_exit_callback=self._on_pid_exit)
        self.jsonl_watcher = JsonlWatcher(on_change_callback=self._on_jsonl_change)

        self.dynamic_menu_keys = []
        self._paused = False
        self._title_counter = {}  # for deduplicating menu titles

        self.menu = [
            rumps.MenuItem('Active Sessions', callback=None),
            rumps.separator,
            rumps.MenuItem('Pause Monitoring', callback=self.toggle_pause),
            rumps.MenuItem('Refresh', callback=self.refresh_sessions),
            rumps.separator,
            rumps.MenuItem('Stats', callback=self.show_stats),
            rumps.separator,
            rumps.MenuItem('Quit', callback=self.quit_app),
        ]

        self.notifier.register_handler(self._handle_notification)

        # Start event-driven subsystems
        self.pid_watcher.start()
        self.jsonl_watcher.start()

        # Seed watchers for any sessions that survived a restart
        active_sessions = self.session_mgr.get_active()
        self.jsonl_watcher.seed_sessions(active_sessions)
        for session in active_sessions:
            pid = session.get('pid')
            if pid:
                self.pid_watcher.watch_pid(int(pid))

        # Start discovery timer (rumps.Timer runs on the main thread)
        self._discovery_timer = rumps.Timer(self._poll_new_processes, DISCOVERY_INTERVAL)
        self._discovery_timer.start()

        self._rebuild_menu()

    # ── Discovery (timer-driven) ──────────────────────────────────────

    def _poll_new_processes(self, _=None):
        """Scan for new Claude Code processes. Runs on rumps Timer."""
        if self._paused:
            return
        active_procs = self.monitor.scan_processes()

        for pid, meta in active_procs.items():
            cid, session = self.session_mgr.find_by_pid(pid, create_time=meta['create_time'])
            if cid is not None:
                # Update IDE if detection improved (e.g. new pattern added)
                if meta['ide'] != 'Terminal' and session.get('ide') == 'Terminal':
                    session['ide'] = meta['ide']
                    self.session_mgr.save_sessions()
                continue

            cwd = meta['cwd'] or ''
            jsonl_path = JsonlParser.find_session_jsonl(cwd, meta['create_time']) if cwd else None
            convo_id = SessionManager.convo_id_for(jsonl_path, pid)

            if convo_id in self.session_mgr.sessions:
                continue

            self._handle_new_session(pid, meta, jsonl_path, convo_id)

        # Check for JSONL that was missing at session creation and retry
        for convo_id, session in list(self.session_mgr.sessions.items()):
            if session['status'] != 'running' or session.get('jsonl'):
                continue
            cwd = session.get('cwd', '')
            if not cwd:
                continue
            jsonl_path = JsonlParser.find_session_jsonl(cwd, session['started_at'])
            if jsonl_path:
                session['jsonl'] = str(jsonl_path)
                # Update title from JSONL
                file_state = self.jsonl_watcher.watch_file(jsonl_path)
                if file_state and file_state.title:
                    session['title'] = file_state.title
                new_id = SessionManager.convo_id_for(jsonl_path, session['pid'])
                self.session_mgr.rekey(convo_id, new_id)

        self._rebuild_menu()

    def _handle_new_session(self, pid, meta, jsonl_path, convo_id):
        """Register a newly discovered session and wire up watchers."""
        title = None
        if jsonl_path:
            file_state = self.jsonl_watcher.watch_file(jsonl_path)
            if file_state:
                title = file_state.title

        self.session_mgr.add_session(
            convo_id=convo_id,
            pid=pid,
            title=title,
            create_time=meta['create_time'],
            ide=meta['ide'],
            cwd=meta['cwd'] or '',
            jsonl_path=jsonl_path,
            tty=meta['tty'],
        )

        self.pid_watcher.watch_pid(int(pid))
        self.notifier.notify(
            f"New session in {meta['ide']}",
            (title or 'New conversation')[:100],
            pid,
        )
        self._rebuild_menu()

    # ── PID exit (kqueue-driven) ──────────────────────────────────────

    def _on_pid_exit(self, pid):
        """Called by PidWatcher from bg thread when a PID exits."""
        callAfter(self._handle_pid_exit, pid)

    def _handle_pid_exit(self, pid):
        """Process a PID exit event on the main thread."""
        pid_str = str(pid)
        cid, session = self.session_mgr.find_by_pid(pid_str)
        if not session:
            return

        # Unwatch JSONL for this session
        jsonl_path = session.get('jsonl', '')
        if jsonl_path:
            self.jsonl_watcher.unwatch_file(jsonl_path)

        if not session.get('notified', False):
            self.notifier.notify(
                "Session completed",
                session.get('title', 'Unknown')[:100],
                session.get('pid'),
            )
        self.session_mgr.complete_session(cid)
        self._rebuild_menu()

    # ── JSONL change (watchdog-driven) ────────────────────────────────

    def _on_jsonl_change(self, path_str, file_state):
        """Called by JsonlWatcher from bg thread when a JSONL file changes."""
        callAfter(self._handle_jsonl_change, path_str, file_state)

    def _handle_jsonl_change(self, path_str, file_state):
        """Process a JSONL change event on the main thread."""
        cid, session = self.session_mgr.find_by_jsonl(path_str)
        if not session:
            return

        changed = False

        # Update title if discovered
        if file_state.title and session.get('title') != file_state.title:
            session['title'] = file_state.title
            changed = True

        # Update state and notify on transitions
        new_state = file_state.state
        prev_state = session.get('last_state', 'active')

        if new_state != prev_state and new_state != 'unknown':
            session['last_state'] = new_state
            changed = True

            if new_state in ('waiting_tool', 'waiting_input') and prev_state == 'active':
                if not self.focus_mgr.is_session_focused(session):
                    title = session.get('title', 'Unknown')[:100]
                    pid = session.get('pid')
                    body = (file_state.latest_response or '').replace('\n', ' ')[:150]
                    if new_state == 'waiting_tool':
                        self.notifier.notify(f"Needs approval in {session['ide']}", title, pid, body)
                    else:
                        self.notifier.notify(f"Waiting for input in {session['ide']}", title, pid, body)

        # Update latest response
        if file_state.latest_response:
            session['latest_response'] = file_state.latest_response
            changed = True

        if changed:
            self.session_mgr.save_sessions()
            self._rebuild_menu()

    # ── Notification click ────────────────────────────────────────────

    def _handle_notification(self, info):
        """Handle notification click — focus the IDE window for the session."""
        pid = info.get('pid') if info else None
        if pid:
            _, session = self.session_mgr.find_by_pid(str(pid))
            if session:
                self.focus_mgr.focus_session(session)

    # ── Menu ──────────────────────────────────────────────────────────

    def _rebuild_menu(self):
        """Rebuild the dynamic portion of the menu bar."""
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
        title_counts = {}

        if active:
            for session in sorted(active, key=lambda x: x['started_at'], reverse=True):
                runtime = self._format_duration(time.time() - session['started_at'])
                title = session.get('title', 'New conversation')
                if len(title) > 40:
                    title = title[:40] + '...'
                ide = session.get('ide', 'Terminal')

                base_label = f"{ide} - {title}  ({runtime})"

                # Deduplicate menu keys with counter suffix
                count = title_counts.get(base_label, 0)
                title_counts[base_label] = count + 1
                title_key = f"{base_label} #{count}" if count > 0 else base_label

                title_item = rumps.MenuItem(
                    title_key,
                    callback=lambda sender, s=session: self.focus_mgr.focus_session(s),
                )
                items_to_add.append((title_key, title_item))

                # Show latest response or state hint
                latest = session.get('latest_response', '')
                if latest:
                    msg_text = latest.replace('\n', ' ')[:70]
                else:
                    file_state = self.jsonl_watcher.get_file_state(session.get('jsonl', ''))
                    if file_state and file_state.latest_response:
                        msg_text = file_state.latest_response.replace('\n', ' ')[:70]
                    else:
                        msg_text = 'Waiting for response...'

                msg_key = f"  {msg_text} #{title_key}"
                msg_item = rumps.MenuItem(msg_key, callback=None)
                items_to_add.append((msg_key, msg_item))
        else:
            items_to_add.append(('No active sessions', rumps.MenuItem('No active sessions', callback=None)))

        for key, item in reversed(items_to_add):
            self.menu.insert_after('Active Sessions', item)
            self.dynamic_menu_keys.append(key)

    # ── UI actions ────────────────────────────────────────────────────

    def toggle_pause(self, sender):
        """Pause or resume monitoring."""
        self._paused = not self._paused
        sender.title = 'Resume Monitoring' if self._paused else 'Pause Monitoring'
        if self._paused:
            self.title = " ⏸"
        else:
            self._rebuild_menu()

    def refresh_sessions(self, _):
        """Manually trigger a process scan."""
        self._poll_new_processes()
        self.notifier.notify('Refreshed', 'Session list updated')

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
        self._discovery_timer.stop()
        self.pid_watcher.stop()
        self.jsonl_watcher.stop()
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
