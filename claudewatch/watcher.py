"""JsonlWatcher — watchdog-based file watcher for Claude JSONL sessions."""

import json
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from claudewatch.jsonl import _strip_xml_tags


class JsonlFileState:
    """Tracks a single JSONL file with incremental reads."""

    def __init__(self, path):
        self.path = Path(path)
        self.last_offset = 0
        self.state = 'unknown'
        self.latest_response = None
        self.title = None

    def refresh(self):
        """Read newly appended bytes and update cached state/response.

        Returns True if state or latest_response changed.
        """
        try:
            size = self.path.stat().st_size
        except OSError:
            return False

        if size <= self.last_offset:
            return False

        old_state = self.state
        old_response = self.latest_response

        try:
            with open(self.path, 'rb') as f:
                f.seek(self.last_offset)
                new_bytes = f.read()
                self.last_offset = f.tell()
        except OSError:
            return False

        text = new_bytes.decode('utf-8', errors='replace')
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            self._process_entry(obj)

        return self.state != old_state or self.latest_response != old_response

    def _process_entry(self, obj):
        """Process a single JSONL entry, updating cached fields."""
        entry_type = obj.get('type')

        # Skip non-message entries — they don't reflect conversational state
        if entry_type not in ('user', 'assistant'):
            return

        msg = obj.get('message', {})
        role = msg.get('role')
        content = msg.get('content', [])

        if role == 'user':
            self.state = 'active'
            # Extract title from first user message
            if self.title is None:
                self._extract_title(content)
            return

        if role == 'assistant':
            if isinstance(content, list) and content:
                block = content[-1]
                if isinstance(block, dict):
                    block_type = block.get('type')
                    if block_type == 'tool_use':
                        self.state = 'waiting_tool'
                    elif block_type == 'text':
                        self.state = 'waiting_input'
                    elif block_type == 'thinking':
                        self.state = 'active'

                # Extract latest text response from any text block
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'text':
                        text = block.get('text', '').strip()
                        if text:
                            self.latest_response = _strip_xml_tags(text)

    def _extract_title(self, content):
        """Extract conversation title from user message content."""
        if isinstance(content, str) and content.strip():
            cleaned = _strip_xml_tags(content)
            if cleaned:
                self.title = cleaned
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'text':
                    text = block.get('text', '').strip()
                    if text:
                        cleaned = _strip_xml_tags(text)
                        if cleaned:
                            self.title = cleaned
                            return


class _DirectoryHandler(FileSystemEventHandler):
    """Forwards on_modified events for tracked .jsonl files to the watcher."""

    def __init__(self, watcher):
        super().__init__()
        self._watcher = watcher

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.jsonl'):
            self._watcher._on_file_modified(event.src_path)


class JsonlWatcher:
    """Manages a watchdog Observer for JSONL file watching."""

    DEBOUNCE_SECONDS = 0.3

    def __init__(self, on_change_callback=None):
        self._on_change = on_change_callback
        self._observer = Observer()
        self._lock = threading.Lock()
        self._file_states = {}          # path_str -> JsonlFileState
        self._watched_dirs = {}         # dir_str -> watch handle
        self._pending_modified = {}     # path_str -> scheduled time
        self._debounce_timer = None

    def start(self):
        """Start the watchdog observer."""
        self._observer.start()

    def stop(self):
        """Stop the watchdog observer."""
        self._observer.stop()
        self._observer.join(timeout=2)
        if self._debounce_timer:
            self._debounce_timer.cancel()

    def watch_file(self, path):
        """Start watching a JSONL file for changes.

        Does an initial refresh to populate cached state.
        """
        path_str = str(path)
        dir_str = str(Path(path).parent)

        with self._lock:
            if path_str in self._file_states:
                return self._file_states[path_str]

            file_state = JsonlFileState(path)
            file_state.refresh()
            self._file_states[path_str] = file_state

            if dir_str not in self._watched_dirs:
                handler = _DirectoryHandler(self)
                watch = self._observer.schedule(handler, dir_str, recursive=False)
                self._watched_dirs[dir_str] = watch

        return file_state

    def unwatch_file(self, path):
        """Stop watching a JSONL file."""
        path_str = str(path)
        dir_str = str(Path(path).parent)

        with self._lock:
            self._file_states.pop(path_str, None)
            self._pending_modified.pop(path_str, None)

            # Unwatch directory if no more files tracked in it
            still_watching = any(
                str(Path(p).parent) == dir_str
                for p in self._file_states
            )
            if not still_watching and dir_str in self._watched_dirs:
                watch = self._watched_dirs.pop(dir_str)
                self._observer.unschedule(watch)

    def get_file_state(self, path):
        """Get the cached JsonlFileState for a path, or None."""
        with self._lock:
            return self._file_states.get(str(path))

    def seed_sessions(self, sessions):
        """Watch JSONL files for all existing active sessions.

        Takes a list of session dicts, each with a 'jsonl' key.
        """
        for session in sessions:
            jsonl_path = session.get('jsonl', '')
            if jsonl_path:
                self.watch_file(jsonl_path)

    def _on_file_modified(self, src_path):
        """Called by _DirectoryHandler when a .jsonl file is modified."""
        path_str = str(src_path)
        with self._lock:
            if path_str not in self._file_states:
                return
            self._pending_modified[path_str] = time.monotonic()

            # Schedule debounced processing (inside lock to prevent race)
            if self._debounce_timer:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(
                self.DEBOUNCE_SECONDS, self._process_pending
            )
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _process_pending(self):
        """Process all pending file modifications after debounce."""
        with self._lock:
            pending = dict(self._pending_modified)
            self._pending_modified.clear()

        for path_str in pending:
            with self._lock:
                file_state = self._file_states.get(path_str)
            if file_state is None:
                continue

            changed = file_state.refresh()
            if changed and self._on_change:
                self._on_change(path_str, file_state)
