"""SessionManager — session state + JSON persistence."""

import json
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
        """Save sessions to disk."""
        with open(self.sessions_file, 'w') as f:
            json.dump(self.sessions, f, indent=2)

    def add_session(self, pid, title, create_time, ide, cwd, jsonl_path, tty):
        """Register a new session."""
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
            'last_state': 'active',
        }
        self.save_sessions()

    def complete_session(self, pid):
        """Mark a session as completed."""
        session = self.sessions.get(pid)
        if session:
            session['status'] = 'completed'
            session['ended_at'] = time.time()
            session['notified'] = True
            self.save_sessions()

    def update_state(self, pid, state):
        """Update the last_state for a session."""
        session = self.sessions.get(pid)
        if session and state != 'unknown':
            session['last_state'] = state
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
