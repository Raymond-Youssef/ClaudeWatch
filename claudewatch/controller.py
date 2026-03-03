"""SessionController — business logic extracted from ClaudeWatch app."""

import time
from pathlib import Path

from claudewatch.jsonl import JsonlParser
from claudewatch.session import SessionManager


class SessionController:
    """Core logic for session discovery, lifecycle, and state management.

    All dependencies are injected — no rumps, objc, or platform imports.
    """

    def __init__(self, session_mgr, notifier, focus_mgr, monitor, pid_watcher, jsonl_watcher):
        self.session_mgr = session_mgr
        self.notifier = notifier
        self.focus_mgr = focus_mgr
        self.monitor = monitor
        self.pid_watcher = pid_watcher
        self.jsonl_watcher = jsonl_watcher
        self._paused = False

    # ── Discovery (timer-driven) ──────────────────────────────────────

    def poll_new_processes(self):
        """Scan for new Claude Code processes.

        Returns True if the menu should be rebuilt.
        """
        if self._paused:
            return False

        active_procs = self.monitor.scan_processes()
        changed = False

        claimed_jsonl = self.session_mgr.get_claimed_jsonl_paths()

        for pid, meta in active_procs.items():
            cid, session = self.session_mgr.find_by_pid(pid, create_time=meta['create_time'])
            if cid is not None:
                session_changed = False
                # Update IDE if detection improved
                if meta['ide'] != 'Terminal' and session.get('ide') == 'Terminal':
                    session['ide'] = meta['ide']
                    session_changed = True
                # Update TTY if it wasn't available at registration
                if not session.get('tty') and meta.get('tty'):
                    session['tty'] = meta['tty']
                    session_changed = True
                if session_changed:
                    self.session_mgr.save_sessions()
                    changed = True
                continue

            cwd = meta['cwd'] or ''
            jsonl_path = JsonlParser.find_session_jsonl(cwd, meta['create_time'], exclude_paths=claimed_jsonl) if cwd else None
            convo_id = SessionManager.convo_id_for(jsonl_path, pid)

            existing = self.session_mgr.sessions.get(convo_id)
            if existing and existing['status'] == 'running':
                # Different PID with same convo_id — use PID-based key
                if str(existing.get('pid')) != str(pid):
                    convo_id = f"pid-{pid}"
                else:
                    continue

            # Re-register if previous session with same convo_id completed
            old = self.session_mgr.sessions.get(convo_id)
            if old and old['status'] != 'running':
                del self.session_mgr.sessions[convo_id]

            self.handle_new_session(pid, meta, jsonl_path, convo_id)
            changed = True

        # Check for JSONL that was missing at session creation and retry
        claimed_jsonl = self.session_mgr.get_claimed_jsonl_paths()
        for convo_id, session in list(self.session_mgr.sessions.items()):
            if session['status'] != 'running':
                continue
            cwd = session.get('cwd', '')
            if not cwd:
                continue

            if not session.get('jsonl'):
                # No JSONL yet — try to find one
                jsonl_path = JsonlParser.find_session_jsonl(cwd, session['started_at'], exclude_paths=claimed_jsonl)
                if jsonl_path:
                    session['jsonl'] = str(jsonl_path)
                    file_state = self.jsonl_watcher.watch_file(jsonl_path)
                    if file_state and file_state.title:
                        session['title'] = file_state.title
                    new_id = SessionManager.convo_id_for(jsonl_path, session['pid'])
                    self.session_mgr.rekey(convo_id, new_id)
                    changed = True
            else:
                # Has JSONL — check if the conversation restarted (e.g. /exit then new chat)
                # by looking for a newer JSONL file in the same project directory
                current_jsonl = Path(session['jsonl'])
                try:
                    current_mtime = current_jsonl.stat().st_mtime
                except OSError:
                    continue
                project_dir = current_jsonl.parent
                newer = [
                    f for f in project_dir.glob('*.jsonl')
                    if f.stat().st_mtime > current_mtime and str(f) not in claimed_jsonl
                ]
                if newer:
                    best = max(newer, key=lambda f: f.stat().st_mtime)
                    if JsonlParser._has_conversation(best):
                        # Switch to the newer JSONL
                        self.jsonl_watcher.unwatch_file(session['jsonl'])
                        session['jsonl'] = str(best)
                        file_state = self.jsonl_watcher.watch_file(best)
                        if file_state and file_state.title:
                            session['title'] = file_state.title
                        session['last_state'] = file_state.state if file_state else 'active'
                        new_id = SessionManager.convo_id_for(best, session['pid'])
                        self.session_mgr.rekey(convo_id, new_id)
                        claimed_jsonl.add(str(best))
                        changed = True

        return changed

    def handle_new_session(self, pid, meta, jsonl_path, convo_id):
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

    # ── PID exit ──────────────────────────────────────────────────────

    def handle_pid_exit(self, pid):
        """Process a PID exit event. Returns True if menu should rebuild."""
        pid_str = str(pid)
        cid, session = self.session_mgr.find_by_pid(pid_str)
        if not session:
            return False

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
        return True

    # ── JSONL change ──────────────────────────────────────────────────

    def handle_jsonl_change(self, path_str, file_state):
        """Process a JSONL change event. Returns True if menu should rebuild."""
        cid, session = self.session_mgr.find_by_jsonl(path_str)
        if not session:
            return False

        changed = False

        if file_state.title and session.get('title') != file_state.title:
            session['title'] = file_state.title
            changed = True

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

        if file_state.latest_response:
            session['latest_response'] = file_state.latest_response
            changed = True

        if changed:
            self.session_mgr.save_sessions()

        return changed

    # ── Notification click ────────────────────────────────────────────

    def handle_notification_click(self, info):
        """Handle notification click — focus the IDE window for the session."""
        pid = info.get('pid') if info else None
        if pid:
            _, session = self.session_mgr.find_by_pid(str(pid))
            if session:
                self.focus_mgr.focus_session(session)

    # ── Menu data ─────────────────────────────────────────────────────

    def get_menu_items(self):
        """Return data for building the menu (no rumps dependency).

        Returns a list of dicts with keys: title_key, label, msg_text,
        icon_path, session.
        """
        active = self.session_mgr.get_active()
        if not active:
            return []

        items = []
        title_counts = {}

        for session in sorted(active, key=lambda x: x['started_at'], reverse=True):
            runtime = format_duration(time.time() - session['started_at'])
            title = session.get('title', 'New conversation')
            if len(title) > 40:
                title = title[:40] + '...'
            ide = session.get('ide', 'Terminal')

            base_label = f"{ide} - {title}  ({runtime})"
            count = title_counts.get(base_label, 0)
            title_counts[base_label] = count + 1
            title_key = f"{base_label} #{count}" if count > 0 else base_label

            latest = session.get('latest_response', '')
            if latest:
                msg_text = latest.replace('\n', ' ')[:70]
            else:
                file_state = self.jsonl_watcher.get_file_state(session.get('jsonl', ''))
                if file_state and file_state.latest_response:
                    msg_text = file_state.latest_response.replace('\n', ' ')[:70]
                else:
                    msg_text = 'Waiting for response...'

            icon_path = self.focus_mgr.get_app_icon(ide)

            items.append({
                'title_key': title_key,
                'label': base_label,
                'msg_text': msg_text,
                'icon_path': icon_path,
                'session': session,
            })

        return items

    def get_title_badge(self):
        """Return the menu bar title badge string."""
        active = self.session_mgr.get_active()
        if active:
            return f" {len(active)}"
        return ""


def format_duration(seconds):
    """Format duration in human readable form."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds / 60)}m"
    else:
        return f"{int(seconds / 3600)}h {int((seconds % 3600) / 60)}m"
