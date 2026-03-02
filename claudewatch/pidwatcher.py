"""PidWatcher — kqueue-based PID exit detection for macOS."""

import errno
import select
import threading


class PidWatcher:
    """Watches PIDs for exit using macOS kqueue EVFILT_PROC.

    Runs a background daemon thread that blocks on kqueue events.
    When a watched PID exits, the on_exit callback is invoked with the PID.
    """

    def __init__(self, on_exit_callback):
        self._on_exit = on_exit_callback
        self._kq = select.kqueue()
        self._lock = threading.Lock()
        self._watched_pids = set()
        self._running = False
        self._thread = None

    def start(self):
        """Start the kqueue polling thread."""
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the polling thread and close the kqueue fd."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        try:
            self._kq.close()
        except OSError:
            pass

    def watch_pid(self, pid):
        """Register a PID for exit monitoring.

        If the PID has already exited, calls back immediately.
        """
        pid = int(pid)
        with self._lock:
            if pid in self._watched_pids:
                return
            self._watched_pids.add(pid)

        ev = select.kevent(
            pid,
            filter=select.KQ_FILTER_PROC,
            flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
            fflags=select.KQ_NOTE_EXIT,
        )
        try:
            self._kq.control([ev], 0, 0)
        except OSError as e:
            if e.errno == errno.ESRCH:
                # PID already exited — fire callback immediately
                with self._lock:
                    self._watched_pids.discard(pid)
                self._on_exit(pid)
            else:
                with self._lock:
                    self._watched_pids.discard(pid)

    def unwatch_pid(self, pid):
        """Stop watching a PID (best-effort removal from kqueue)."""
        pid = int(pid)
        with self._lock:
            self._watched_pids.discard(pid)
        # KQ_EV_DELETE to deregister; ignore errors if PID already exited
        ev = select.kevent(
            pid,
            filter=select.KQ_FILTER_PROC,
            flags=select.KQ_EV_DELETE,
        )
        try:
            self._kq.control([ev], 0, 0)
        except OSError:
            pass

    def _loop(self):
        """Block on kqueue events and dispatch exit callbacks."""
        while self._running:
            try:
                events = self._kq.control([], 4, 1.0)
            except OSError:
                if not self._running:
                    break
                continue

            for ev in events:
                pid = ev.ident
                if ev.fflags & select.KQ_NOTE_EXIT:
                    with self._lock:
                        self._watched_pids.discard(pid)
                    self._on_exit(pid)
