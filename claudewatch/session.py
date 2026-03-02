"""SessionManager — session state + JSON persistence."""

import json
import os
import tempfile
import time
from pathlib import Path


class SessionManager:
    def __init__(self):
        self.data_dir = Path.home() / '.claudewatch'
        self.data_dir.mkdir(exist_ok=True)
        self.sessions_file = self.data_dir / 'sessions.json'
        self.sessions = self.load_sessions()

    def load_sessions(self):
        """Load sessions from disk."""
        if self.sessions_file.exists():
            try:
                with open(self.sessions_file, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_sessions(self):
        """Save sessions to disk atomically via temp file + rename."""
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self.data_dir), suffix='.tmp'
            )
            with os.fdopen(fd, 'w') as f:
                json.dump(self.sessions, f, indent=2)
            os.replace(tmp_path, str(self.sessions_file))
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    @staticmethod
    def convo_id_for(jsonl_path, pid):
        """Derive a conversation ID: JSONL stem UUID if available, else pid-{pid}."""
        if jsonl_path:
            return Path(jsonl_path).stem
        return f"pid-{pid}"

    def add_session(self, convo_id, pid, title, create_time, ide, cwd, jsonl_path, tty):
        """Register a new session keyed by conversation ID."""
        self.sessions[convo_id] = {
            'convo_id': convo_id,
            'pid': pid,
            'title': title or 'New conversation',
            'started_at': create_time,
            'status': 'running',
            'ide': ide,
            'cwd': cwd,
            'jsonl': str(jsonl_path) if jsonl_path else '',
            'tty': tty,
            'notified': False,
            'last_state': 'active',
        }
        self.save_sessions()

    def complete_session(self, convo_id):
        """Mark a session as completed."""
        session = self.sessions.get(convo_id)
        if session:
            session['status'] = 'completed'
            session['ended_at'] = time.time()
            session['notified'] = True
            self.save_sessions()

    def update_state(self, convo_id, state):
        """Update the last_state for a session."""
        session = self.sessions.get(convo_id)
        if session and state != 'unknown':
            session['last_state'] = state
            self.save_sessions()

    def prune_old_sessions(self, max_age=86400 * 7):
        """Remove completed sessions older than max_age seconds."""
        cutoff = time.time() - max_age
        to_remove = [
            cid for cid, s in self.sessions.items()
            if s['status'] == 'completed' and s.get('ended_at', 0) < cutoff
        ]
        if to_remove:
            for cid in to_remove:
                del self.sessions[cid]
            self.save_sessions()

    def find_by_pid(self, pid, create_time=None):
        """Find an active session by its PID. Returns (convo_id, session) or (None, None).

        If create_time is provided, rejects matches where the session's started_at
        differs by more than 2 seconds (guards against PID reuse).
        """
        for cid, session in self.sessions.items():
            if session.get('pid') == pid and session['status'] == 'running':
                if create_time is not None:
                    if abs(session['started_at'] - create_time) > 2:
                        continue
                return cid, session
        return None, None

    def find_by_jsonl(self, jsonl_path):
        """Find an active session by its JSONL path. Returns (convo_id, session) or (None, None)."""
        path_str = str(jsonl_path)
        for cid, session in self.sessions.items():
            if session.get('jsonl') == path_str and session['status'] == 'running':
                return cid, session
        return None, None

    def rekey(self, old_id, new_id):
        """Re-key a session (e.g. when JSONL is discovered for a pid-keyed session)."""
        if old_id == new_id or old_id not in self.sessions:
            return
        session = self.sessions.pop(old_id)
        session['convo_id'] = new_id
        self.sessions[new_id] = session
        self.save_sessions()

    def get_active(self):
        """Return list of sessions with status 'running'."""
        return [s for s in self.sessions.values() if s['status'] == 'running']

    def get_completed_today(self):
        """Return sessions completed in the last 24 hours."""
        cutoff = time.time() - 86400
        return [s for s in self.sessions.values()
                if s['status'] == 'completed' and s.get('ended_at', 0) > cutoff]

    def get_stats(self):
        """Return stats dict with active, completed_today, total counts."""
        active = self.get_active()
        completed_today = self.get_completed_today()
        return {
            'active': len(active),
            'completed_today': len(completed_today),
            'total': len(self.sessions),
            'avg_duration': (
                sum(s.get('ended_at', 0) - s['started_at'] for s in completed_today) / len(completed_today)
                if completed_today else 0
            ),
        }
