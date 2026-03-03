"""ClaudeWatch(rumps.App) — thin menu bar shell delegating to SessionController."""

import os
import sys

import rumps
from PyObjCTools.AppHelper import callAfter

from claudewatch.controller import SessionController, format_duration
from claudewatch.focus import FocusManager
from claudewatch.monitor import ProcessMonitor
from claudewatch.notifications import Notifier
from claudewatch.pidwatcher import PidWatcher
from claudewatch.session import SessionManager
from claudewatch.watcher import JsonlWatcher

APP_NAME = 'ClaudeWatch'
DISCOVERY_INTERVAL = 5  # seconds between process scans


class ClaudeWatch(rumps.App):
    def __init__(self):
        if getattr(sys, 'frozen', False):
            icon_path = os.path.join(os.environ.get('RESOURCEPATH', ''), 'icon.png')
        else:
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'icon.png')
        super(ClaudeWatch, self).__init__("ClaudeWatch", icon=icon_path, quit_button=None)

        session_mgr = SessionManager()
        session_mgr.prune_old_sessions()

        notifier = Notifier()
        focus_mgr = FocusManager()
        monitor = ProcessMonitor()

        pid_watcher = PidWatcher(on_exit_callback=self._on_pid_exit)
        jsonl_watcher = JsonlWatcher(on_change_callback=self._on_jsonl_change)

        self.ctrl = SessionController(
            session_mgr=session_mgr,
            notifier=notifier,
            focus_mgr=focus_mgr,
            monitor=monitor,
            pid_watcher=pid_watcher,
            jsonl_watcher=jsonl_watcher,
        )

        self.dynamic_menu_keys = []

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

        notifier.register_handler(self.ctrl.handle_notification_click)

        # Start event-driven subsystems
        pid_watcher.start()
        jsonl_watcher.start()

        # Seed watchers for any sessions that survived a restart
        active_sessions = session_mgr.get_active()
        jsonl_watcher.seed_sessions(active_sessions)
        for session in active_sessions:
            pid = session.get('pid')
            if pid:
                pid_watcher.watch_pid(int(pid))

        self._discovery_timer = rumps.Timer(self._poll_new_processes, DISCOVERY_INTERVAL)
        self._discovery_timer.start()

        self._rebuild_menu()

    # ── Event callbacks (bridge bg threads → main thread → controller) ─

    def _poll_new_processes(self, _=None):
        if self.ctrl.poll_new_processes():
            self._rebuild_menu()

    def _on_pid_exit(self, pid):
        callAfter(self._handle_pid_exit, pid)

    def _handle_pid_exit(self, pid):
        if self.ctrl.handle_pid_exit(pid):
            self._rebuild_menu()

    def _on_jsonl_change(self, path_str, file_state):
        callAfter(self._handle_jsonl_change, path_str, file_state)

    def _handle_jsonl_change(self, path_str, file_state):
        if self.ctrl.handle_jsonl_change(path_str, file_state):
            self._rebuild_menu()

    # ── Menu rendering ────────────────────────────────────────────────

    def _rebuild_menu(self):
        for key in self.dynamic_menu_keys:
            try:
                del self.menu[key]
            except KeyError:
                pass
        self.dynamic_menu_keys = []

        self.title = self.ctrl.get_title_badge()
        items = self.ctrl.get_menu_items()

        items_to_add = []
        if items:
            for item in items:
                title_key = item['title_key']
                title_item = rumps.MenuItem(
                    title_key,
                    callback=lambda sender, s=item['session']: self.ctrl.focus_mgr.focus_session(s),
                    icon=item['icon_path'],
                    dimensions=(18, 18),
                )
                items_to_add.append((title_key, title_item))

                msg_key = f"  {item['msg_text']} #{title_key}"
                msg_item = rumps.MenuItem(msg_key, callback=None)
                items_to_add.append((msg_key, msg_item))
        else:
            items_to_add.append(('No active sessions', rumps.MenuItem('No active sessions', callback=None)))

        for key, item in reversed(items_to_add):
            self.menu.insert_after('Active Sessions', item)
            self.dynamic_menu_keys.append(key)

    # ── UI actions ────────────────────────────────────────────────────

    def toggle_pause(self, sender):
        self.ctrl._paused = not self.ctrl._paused
        sender.title = 'Resume Monitoring' if self.ctrl._paused else 'Pause Monitoring'
        if self.ctrl._paused:
            self.title = " ⏸"
        else:
            self._rebuild_menu()

    def refresh_sessions(self, _):
        self.ctrl.poll_new_processes()
        self._rebuild_menu()
        self.ctrl.notifier.notify('Refreshed', 'Session list updated')

    def show_stats(self, _):
        stats = self.ctrl.session_mgr.get_stats()
        msg = f"Active sessions: {stats['active']}\n"
        msg += f"Completed today: {stats['completed_today']}\n"
        msg += f"Total tracked: {stats['total']}\n\n"
        if stats['avg_duration']:
            msg += f"Avg session time today: {format_duration(stats['avg_duration'])}"
        rumps.alert(APP_NAME, msg)

    def quit_app(self, _):
        self._discovery_timer.stop()
        self.ctrl.pid_watcher.stop()
        self.ctrl.jsonl_watcher.stop()
        rumps.quit_application()
