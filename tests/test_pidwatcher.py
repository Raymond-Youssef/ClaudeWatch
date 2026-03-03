"""Tests for claudewatch.pidwatcher — PidWatcher (kqueue-based PID exit detection)."""

import errno
import threading
from unittest.mock import MagicMock, patch, call

import pytest

from claudewatch.pidwatcher import PidWatcher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_watcher(callback=None):
    """Create a PidWatcher with kqueue replaced by a MagicMock.

    Returns (watcher, mock_kq, callback).
    """
    cb = callback or MagicMock()
    with patch('claudewatch.pidwatcher.select') as mock_select:
        mock_kq = MagicMock()
        mock_select.kqueue.return_value = mock_kq
        watcher = PidWatcher(on_exit_callback=cb)
    # At this point watcher._kq is mock_kq; no live kqueue fd exists.
    return watcher, mock_kq, cb


def _make_exit_event(pid):
    """Create a mock kevent object representing a KQ_NOTE_EXIT event."""
    import select as _sel
    ev = MagicMock()
    ev.ident = pid
    ev.fflags = _sel.KQ_NOTE_EXIT
    return ev


# ===========================================================================
# watch_pid
# ===========================================================================

class TestWatchPid:
    """PidWatcher.watch_pid registers a PID via kqueue kevent."""

    def test_registers_pid_in_watched_set(self):
        watcher, mock_kq, _ = _make_watcher()
        watcher.watch_pid(12345)
        assert 12345 in watcher._watched_pids

    def test_calls_kq_control_with_kevent(self):
        watcher, mock_kq, _ = _make_watcher()
        watcher.watch_pid(12345)
        mock_kq.control.assert_called_once()
        args, _ = mock_kq.control.call_args
        # control([kevent], 0, 0)
        assert args[1] == 0
        assert args[2] == 0
        assert len(args[0]) == 1

    def test_duplicate_pid_is_ignored(self):
        watcher, mock_kq, _ = _make_watcher()
        watcher.watch_pid(12345)
        mock_kq.control.reset_mock()

        # Second call with same PID should return early
        watcher.watch_pid(12345)
        mock_kq.control.assert_not_called()
        assert 12345 in watcher._watched_pids

    def test_esrch_fires_callback_immediately(self):
        """When PID already exited (ESRCH), callback fires and PID is discarded."""
        callback = MagicMock()
        watcher, mock_kq, _ = _make_watcher(callback=callback)

        mock_kq.control.side_effect = OSError(errno.ESRCH, 'No such process')

        watcher.watch_pid(99999)

        callback.assert_called_once_with(99999)
        assert 99999 not in watcher._watched_pids

    def test_other_oserror_discards_pid_without_callback(self):
        """Non-ESRCH OSError discards PID but does NOT fire callback."""
        callback = MagicMock()
        watcher, mock_kq, _ = _make_watcher(callback=callback)

        mock_kq.control.side_effect = OSError(errno.EPERM, 'Operation not permitted')

        watcher.watch_pid(88888)

        callback.assert_not_called()
        assert 88888 not in watcher._watched_pids

    def test_pid_is_coerced_to_int(self):
        """String PIDs are converted to int before registration."""
        watcher, mock_kq, _ = _make_watcher()
        watcher.watch_pid('12345')
        assert 12345 in watcher._watched_pids

    def test_multiple_distinct_pids(self):
        """Multiple different PIDs can all be registered."""
        watcher, mock_kq, _ = _make_watcher()
        watcher.watch_pid(100)
        watcher.watch_pid(200)
        watcher.watch_pid(300)

        assert {100, 200, 300} == watcher._watched_pids
        assert mock_kq.control.call_count == 3


# ===========================================================================
# unwatch_pid
# ===========================================================================

class TestUnwatchPid:
    """PidWatcher.unwatch_pid removes a PID from tracking."""

    def test_removes_pid_from_watched_set(self):
        watcher, mock_kq, _ = _make_watcher()
        watcher._watched_pids.add(12345)

        watcher.unwatch_pid(12345)

        assert 12345 not in watcher._watched_pids

    def test_sends_kq_ev_delete_kevent(self):
        watcher, mock_kq, _ = _make_watcher()
        watcher._watched_pids.add(12345)

        watcher.unwatch_pid(12345)

        mock_kq.control.assert_called_once()
        args, _ = mock_kq.control.call_args
        assert args[1] == 0
        assert args[2] == 0

    def test_ignores_oserror_on_delete(self):
        """KQ_EV_DELETE is best-effort; OSError is swallowed."""
        watcher, mock_kq, _ = _make_watcher()
        watcher._watched_pids.add(12345)
        mock_kq.control.side_effect = OSError(errno.ESRCH, 'No such process')

        # Should not raise
        watcher.unwatch_pid(12345)
        assert 12345 not in watcher._watched_pids

    def test_unwatch_pid_not_in_set(self):
        """Unwatching a PID that was never watched is a no-op for the set."""
        watcher, mock_kq, _ = _make_watcher()
        # Should not raise
        watcher.unwatch_pid(99999)
        assert 99999 not in watcher._watched_pids

    def test_pid_is_coerced_to_int(self):
        watcher, mock_kq, _ = _make_watcher()
        watcher._watched_pids.add(12345)
        watcher.unwatch_pid('12345')
        assert 12345 not in watcher._watched_pids


# ===========================================================================
# _loop
# ===========================================================================

class TestLoop:
    """PidWatcher._loop blocks on kqueue and dispatches exit callbacks."""

    def test_dispatches_callback_on_exit_event(self):
        """When kqueue returns a KQ_NOTE_EXIT event, callback fires."""
        import select as _sel

        callback = MagicMock()
        watcher, mock_kq, _ = _make_watcher(callback=callback)
        watcher._watched_pids.add(42)

        exit_event = MagicMock()
        exit_event.ident = 42
        exit_event.fflags = _sel.KQ_NOTE_EXIT

        # First call returns exit event, second call triggers loop exit
        call_count = 0
        def control_side_effect(changelist, max_events, timeout):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [exit_event]
            # Stop the loop on the next iteration
            watcher._running = False
            return []

        mock_kq.control.side_effect = control_side_effect
        watcher._running = True
        watcher._loop()

        callback.assert_called_once_with(42)
        assert 42 not in watcher._watched_pids

    def test_removes_pid_from_watched_on_exit(self):
        """PID is removed from _watched_pids when exit event fires."""
        import select as _sel

        callback = MagicMock()
        watcher, mock_kq, _ = _make_watcher(callback=callback)
        watcher._watched_pids.update({10, 20, 30})

        exit_event = MagicMock()
        exit_event.ident = 20
        exit_event.fflags = _sel.KQ_NOTE_EXIT

        call_count = 0
        def control_side_effect(changelist, max_events, timeout):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [exit_event]
            watcher._running = False
            return []

        mock_kq.control.side_effect = control_side_effect
        watcher._running = True
        watcher._loop()

        # Only PID 20 should have been removed
        assert 20 not in watcher._watched_pids
        assert 10 in watcher._watched_pids
        assert 30 in watcher._watched_pids

    def test_continues_on_oserror_when_running(self):
        """OSError during kqueue.control continues looping if _running is True."""
        callback = MagicMock()
        watcher, mock_kq, _ = _make_watcher(callback=callback)

        call_count = 0
        def control_side_effect(changelist, max_events, timeout):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError(errno.EINTR, 'Interrupted')
            # Stop after second iteration
            watcher._running = False
            return []

        mock_kq.control.side_effect = control_side_effect
        watcher._running = True
        watcher._loop()

        # Loop continued past the OSError and made a second call
        assert call_count == 2
        callback.assert_not_called()

    def test_exits_loop_on_oserror_when_not_running(self):
        """OSError during kqueue.control breaks loop if _running is False."""
        callback = MagicMock()
        watcher, mock_kq, _ = _make_watcher(callback=callback)

        def control_side_effect(changelist, max_events, timeout):
            watcher._running = False
            raise OSError(errno.EBADF, 'Bad file descriptor')

        mock_kq.control.side_effect = control_side_effect
        watcher._running = True
        watcher._loop()

        callback.assert_not_called()

    def test_exits_loop_when_running_set_false(self):
        """Loop terminates when _running becomes False between iterations."""
        watcher, mock_kq, _ = _make_watcher()

        call_count = 0
        def control_side_effect(changelist, max_events, timeout):
            nonlocal call_count
            call_count += 1
            watcher._running = False
            return []

        mock_kq.control.side_effect = control_side_effect
        watcher._running = True
        watcher._loop()

        assert call_count == 1

    def test_multiple_exit_events_in_single_batch(self):
        """Multiple exit events returned from one kqueue.control call."""
        import select as _sel

        callback = MagicMock()
        watcher, mock_kq, _ = _make_watcher(callback=callback)
        watcher._watched_pids.update({10, 20})

        ev1 = MagicMock()
        ev1.ident = 10
        ev1.fflags = _sel.KQ_NOTE_EXIT

        ev2 = MagicMock()
        ev2.ident = 20
        ev2.fflags = _sel.KQ_NOTE_EXIT

        call_count = 0
        def control_side_effect(changelist, max_events, timeout):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [ev1, ev2]
            watcher._running = False
            return []

        mock_kq.control.side_effect = control_side_effect
        watcher._running = True
        watcher._loop()

        assert callback.call_count == 2
        callback.assert_any_call(10)
        callback.assert_any_call(20)
        assert 10 not in watcher._watched_pids
        assert 20 not in watcher._watched_pids

    def test_event_without_note_exit_is_ignored(self):
        """Events that do not have KQ_NOTE_EXIT fflags are ignored."""
        import select as _sel

        callback = MagicMock()
        watcher, mock_kq, _ = _make_watcher(callback=callback)
        watcher._watched_pids.add(42)

        non_exit_event = MagicMock()
        non_exit_event.ident = 42
        non_exit_event.fflags = 0  # Not KQ_NOTE_EXIT

        call_count = 0
        def control_side_effect(changelist, max_events, timeout):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [non_exit_event]
            watcher._running = False
            return []

        mock_kq.control.side_effect = control_side_effect
        watcher._running = True
        watcher._loop()

        callback.assert_not_called()
        # PID should still be watched since it was not an exit event
        assert 42 in watcher._watched_pids


# ===========================================================================
# Lifecycle: start() / stop()
# ===========================================================================

class TestLifecycle:
    """PidWatcher.start() and stop() manage the daemon thread and kqueue fd."""

    def test_start_creates_daemon_thread(self):
        watcher, mock_kq, _ = _make_watcher()

        started = threading.Event()

        def control_side_effect(changelist, max_events, timeout):
            started.set()
            # Block until stop() clears _running
            while watcher._running:
                pass
            return []

        mock_kq.control.side_effect = control_side_effect

        watcher.start()
        started.wait(timeout=2)

        assert watcher._thread is not None
        assert watcher._thread.daemon is True
        assert watcher._running is True

        # Clean up
        watcher._running = False
        watcher._thread.join(timeout=2)

    def test_start_sets_running_true(self):
        watcher, mock_kq, _ = _make_watcher()
        mock_kq.control.side_effect = lambda *args: (
            setattr(watcher, '_running', False) or []
        )

        assert watcher._running is False
        watcher.start()
        # _running was set to True before the thread flipped it back
        # We can verify the thread was started
        assert watcher._thread is not None
        watcher._thread.join(timeout=2)

    def test_stop_sets_running_false(self):
        watcher, mock_kq, _ = _make_watcher()
        watcher._running = True
        watcher._thread = MagicMock()

        watcher.stop()

        assert watcher._running is False

    def test_stop_joins_thread(self):
        watcher, mock_kq, _ = _make_watcher()
        mock_thread = MagicMock()
        watcher._thread = mock_thread
        watcher._running = True

        watcher.stop()

        mock_thread.join.assert_called_once_with(timeout=2)

    def test_stop_closes_kqueue_fd(self):
        watcher, mock_kq, _ = _make_watcher()
        watcher._thread = MagicMock()
        watcher._running = True

        watcher.stop()

        mock_kq.close.assert_called_once()

    def test_stop_ignores_oserror_on_close(self):
        """OSError when closing kqueue fd is swallowed."""
        watcher, mock_kq, _ = _make_watcher()
        watcher._thread = MagicMock()
        watcher._running = True
        mock_kq.close.side_effect = OSError(errno.EBADF, 'Bad file descriptor')

        # Should not raise
        watcher.stop()

    def test_stop_without_thread(self):
        """stop() is safe to call even if start() was never called."""
        watcher, mock_kq, _ = _make_watcher()
        assert watcher._thread is None

        # Should not raise
        watcher.stop()
        mock_kq.close.assert_called_once()

    def test_full_start_stop_cycle(self):
        """Integration: start, wait for thread to begin, then stop cleanly."""
        callback = MagicMock()
        watcher, mock_kq, _ = _make_watcher(callback=callback)

        started = threading.Event()

        original_side_effect_calls = 0
        def control_side_effect(changelist, max_events, timeout):
            nonlocal original_side_effect_calls
            original_side_effect_calls += 1
            if original_side_effect_calls == 1:
                started.set()
            if not watcher._running:
                raise OSError(errno.EBADF, 'closed')
            return []

        mock_kq.control.side_effect = control_side_effect

        watcher.start()
        started.wait(timeout=2)
        watcher.stop()

        assert watcher._running is False
        callback.assert_not_called()


# ===========================================================================
# __init__
# ===========================================================================

class TestInit:
    """PidWatcher.__init__ sets up internal state correctly."""

    def test_initial_state(self):
        watcher, mock_kq, callback = _make_watcher()

        assert watcher._on_exit is callback
        assert watcher._kq is mock_kq
        assert isinstance(watcher._lock, type(threading.Lock()))
        assert watcher._watched_pids == set()
        assert watcher._running is False
        assert watcher._thread is None
