"""Tests for claudewatch.controller.SessionController and format_duration."""

import time
from unittest.mock import MagicMock, patch, call

import pytest

from claudewatch.controller import SessionController, format_duration


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_controller():
    """Create a SessionController with all deps mocked."""
    ctrl = SessionController(
        session_mgr=MagicMock(),
        notifier=MagicMock(),
        focus_mgr=MagicMock(),
        monitor=MagicMock(),
        pid_watcher=MagicMock(),
        jsonl_watcher=MagicMock(),
    )
    # Default: session_mgr.sessions is a real dict
    ctrl.session_mgr.sessions = {}
    return ctrl


def _flush_notify_timers(ctrl):
    """Run and wait for all pending notification timers."""
    for timer in list(ctrl._notify_timers.values()):
        timer.join(timeout=2)


def _proc(pid='12345', create_time=1000.0, cwd='/tmp/project',
          ide='VS Code', tty='/dev/ttys001'):
    """Build a process-info dict as returned by monitor.scan_processes."""
    return {
        'create_time': create_time,
        'cwd': cwd,
        'ide': ide,
        'tty': tty,
        'cmdline': ['claude'],
    }


def _session(convo_id='test-uuid', pid='12345', status='running',
             ide='VS Code', title='Test conversation', tty='/dev/ttys001',
             jsonl='/tmp/test.jsonl', started_at=None, notified=False,
             last_state='active', cwd='/tmp/project', **extra):
    """Build a session dict with sensible defaults."""
    s = {
        'convo_id': convo_id,
        'pid': pid,
        'title': title,
        'started_at': started_at or (time.time() - 300),
        'status': status,
        'ide': ide,
        'cwd': cwd,
        'jsonl': jsonl,
        'tty': tty,
        'notified': notified,
        'last_state': last_state,
    }
    s.update(extra)
    return s


# ===========================================================================
# format_duration (module-level function, pure)
# ===========================================================================

class TestFormatDuration:
    def test_zero_seconds(self):
        assert format_duration(0) == "0s"

    def test_under_60_seconds(self):
        assert format_duration(30) == "30s"

    def test_exactly_one_second(self):
        assert format_duration(1) == "1s"

    def test_59_seconds(self):
        assert format_duration(59) == "59s"

    def test_exactly_60_seconds(self):
        assert format_duration(60) == "1m"

    def test_minutes_range(self):
        assert format_duration(120) == "2m"
        assert format_duration(3599) == "59m"

    def test_exactly_3600_seconds(self):
        assert format_duration(3600) == "1h 0m"

    def test_hours_and_minutes(self):
        assert format_duration(3660) == "1h 1m"
        assert format_duration(7200) == "2h 0m"
        assert format_duration(7260) == "2h 1m"

    def test_large_duration(self):
        assert format_duration(36000) == "10h 0m"


# ===========================================================================
# poll_new_processes
# ===========================================================================

class TestPollNewProcesses:
    def test_returns_false_when_paused(self):
        ctrl = make_controller()
        ctrl._paused = True
        ctrl.monitor.scan_processes.return_value = {
            '12345': _proc(),
        }
        assert ctrl.poll_new_processes() is False
        ctrl.monitor.scan_processes.assert_not_called()

    def test_discovers_new_process(self):
        ctrl = make_controller()
        ctrl.session_mgr.find_by_pid.return_value = (None, None)

        ctrl.monitor.scan_processes.return_value = {
            '12345': _proc(),
        }

        with patch('claudewatch.controller.JsonlParser') as mock_jp, \
             patch('claudewatch.controller.SessionManager') as mock_sm_cls:
            mock_jp.find_session_jsonl.return_value = '/path/to/session.jsonl'
            mock_sm_cls.convo_id_for.return_value = 'test-uuid'

            result = ctrl.poll_new_processes()

        assert result is True
        ctrl.session_mgr.add_session.assert_called_once()
        ctrl.pid_watcher.watch_pid.assert_called_once_with(12345)
        ctrl.notifier.notify.assert_called_once()

    def test_known_process_skips(self):
        ctrl = make_controller()
        existing_session = _session(ide='VS Code')
        ctrl.session_mgr.find_by_pid.return_value = ('test-uuid', existing_session)

        ctrl.monitor.scan_processes.return_value = {
            '12345': _proc(ide='VS Code'),
        }

        result = ctrl.poll_new_processes()
        assert result is False
        ctrl.session_mgr.add_session.assert_not_called()

    def test_ide_update_terminal_to_vscode(self):
        ctrl = make_controller()
        existing_session = _session(ide='Terminal')
        ctrl.session_mgr.find_by_pid.return_value = ('test-uuid', existing_session)

        ctrl.monitor.scan_processes.return_value = {
            '12345': _proc(ide='VS Code'),
        }

        result = ctrl.poll_new_processes()
        assert result is True
        assert existing_session['ide'] == 'VS Code'
        ctrl.session_mgr.save_sessions.assert_called()

    def test_ide_no_update_when_scan_says_terminal(self):
        """If scan returns Terminal but session already has VS Code, no change."""
        ctrl = make_controller()
        existing_session = _session(ide='VS Code')
        ctrl.session_mgr.find_by_pid.return_value = ('test-uuid', existing_session)

        ctrl.monitor.scan_processes.return_value = {
            '12345': _proc(ide='Terminal'),
        }

        result = ctrl.poll_new_processes()
        assert result is False
        assert existing_session['ide'] == 'VS Code'

    def test_tty_backfill(self):
        ctrl = make_controller()
        existing_session = _session(tty='')
        ctrl.session_mgr.find_by_pid.return_value = ('test-uuid', existing_session)

        ctrl.monitor.scan_processes.return_value = {
            '12345': _proc(tty='/dev/ttys005'),
        }

        result = ctrl.poll_new_processes()
        assert result is True
        assert existing_session['tty'] == '/dev/ttys005'
        ctrl.session_mgr.save_sessions.assert_called()

    def test_tty_no_backfill_when_already_set(self):
        ctrl = make_controller()
        existing_session = _session(tty='/dev/ttys001')
        ctrl.session_mgr.find_by_pid.return_value = ('test-uuid', existing_session)

        ctrl.monitor.scan_processes.return_value = {
            '12345': _proc(tty='/dev/ttys005'),
        }

        result = ctrl.poll_new_processes()
        assert result is False
        assert existing_session['tty'] == '/dev/ttys001'

    def test_convo_id_collision_uses_pid_key(self):
        """Different PID with same convo_id uses pid-{pid} key."""
        ctrl = make_controller()
        ctrl.session_mgr.find_by_pid.return_value = (None, None)

        # Existing running session with a different PID but same convo_id
        ctrl.session_mgr.sessions = {
            'test-uuid': _session(convo_id='test-uuid', pid='99999', status='running'),
        }

        ctrl.monitor.scan_processes.return_value = {
            '12345': _proc(),
        }

        with patch('claudewatch.controller.JsonlParser') as mock_jp, \
             patch('claudewatch.controller.SessionManager') as mock_sm_cls:
            mock_jp.find_session_jsonl.return_value = '/path/to/session.jsonl'
            mock_sm_cls.convo_id_for.return_value = 'test-uuid'

            ctrl.poll_new_processes()

        # Should use pid-based key instead
        add_call = ctrl.session_mgr.add_session.call_args
        assert add_call is not None
        # The first positional or keyword arg for convo_id should be pid-12345
        # handle_new_session is called with convo_id=f"pid-{pid}"
        ctrl.notifier.notify.assert_called_once()

    def test_completed_session_with_same_convo_id_replaces(self):
        """Completed session with same convo_id is deleted and new one registered."""
        ctrl = make_controller()
        ctrl.session_mgr.find_by_pid.return_value = (None, None)

        ctrl.session_mgr.sessions = {
            'test-uuid': _session(convo_id='test-uuid', pid='99999', status='completed'),
        }

        ctrl.monitor.scan_processes.return_value = {
            '12345': _proc(),
        }

        with patch('claudewatch.controller.JsonlParser') as mock_jp, \
             patch('claudewatch.controller.SessionManager') as mock_sm_cls:
            mock_jp.find_session_jsonl.return_value = '/path/to/session.jsonl'
            mock_sm_cls.convo_id_for.return_value = 'test-uuid'

            result = ctrl.poll_new_processes()

        assert result is True
        # The old completed session should be removed before handle_new_session
        # (it's deleted via `del self.session_mgr.sessions[convo_id]`)
        assert 'test-uuid' not in ctrl.session_mgr.sessions

    def test_same_pid_same_convo_id_running_skips(self):
        """Same PID and same convo_id for a running session skips entirely."""
        ctrl = make_controller()
        ctrl.session_mgr.find_by_pid.return_value = (None, None)

        ctrl.session_mgr.sessions = {
            'test-uuid': _session(convo_id='test-uuid', pid='12345', status='running'),
        }

        ctrl.monitor.scan_processes.return_value = {
            '12345': _proc(),
        }

        with patch('claudewatch.controller.JsonlParser') as mock_jp, \
             patch('claudewatch.controller.SessionManager') as mock_sm_cls:
            mock_jp.find_session_jsonl.return_value = '/path/to/session.jsonl'
            mock_sm_cls.convo_id_for.return_value = 'test-uuid'

            result = ctrl.poll_new_processes()

        assert result is False
        ctrl.session_mgr.add_session.assert_not_called()

    def test_jsonl_retry_discovers_missing_jsonl(self):
        """Session missing JSONL gets it populated on later poll."""
        ctrl = make_controller()
        ctrl.session_mgr.find_by_pid.return_value = (None, None)
        ctrl.monitor.scan_processes.return_value = {}

        # Session without JSONL
        ctrl.session_mgr.sessions = {
            'pid-12345': _session(
                convo_id='pid-12345', pid='12345', jsonl='',
                cwd='/tmp/project', started_at=1000.0,
            ),
        }

        mock_file_state = MagicMock()
        mock_file_state.title = 'Discovered title'
        ctrl.jsonl_watcher.watch_file.return_value = mock_file_state

        with patch('claudewatch.controller.JsonlParser') as mock_jp, \
             patch('claudewatch.controller.SessionManager') as mock_sm_cls:
            mock_jp.find_session_jsonl.return_value = '/path/to/discovered.jsonl'
            mock_sm_cls.convo_id_for.return_value = 'new-convo-uuid'

            result = ctrl.poll_new_processes()

        assert result is True
        session = ctrl.session_mgr.sessions['pid-12345']
        assert session['jsonl'] == '/path/to/discovered.jsonl'
        assert session['title'] == 'Discovered title'
        ctrl.jsonl_watcher.watch_file.assert_called_once_with('/path/to/discovered.jsonl')
        ctrl.session_mgr.rekey.assert_called_once_with('pid-12345', 'new-convo-uuid')

    def test_jsonl_retry_skips_completed_sessions(self):
        """JSONL retry only applies to running sessions."""
        ctrl = make_controller()
        ctrl.monitor.scan_processes.return_value = {}
        ctrl.session_mgr.find_by_pid.return_value = (None, None)

        ctrl.session_mgr.sessions = {
            'pid-99': _session(
                convo_id='pid-99', pid='99', jsonl='', status='completed',
            ),
        }

        with patch('claudewatch.controller.JsonlParser') as mock_jp:
            mock_jp.find_session_jsonl.return_value = '/path/to/file.jsonl'
            result = ctrl.poll_new_processes()

        assert result is False
        ctrl.jsonl_watcher.watch_file.assert_not_called()

    def test_jsonl_retry_skips_if_already_has_jsonl(self):
        """JSONL retry skips sessions that already have a JSONL path."""
        ctrl = make_controller()
        ctrl.monitor.scan_processes.return_value = {}
        ctrl.session_mgr.find_by_pid.return_value = (None, None)

        ctrl.session_mgr.sessions = {
            'uuid-1': _session(
                convo_id='uuid-1', pid='100', jsonl='/existing.jsonl',
            ),
        }

        with patch('claudewatch.controller.JsonlParser') as mock_jp:
            result = ctrl.poll_new_processes()

        assert result is False
        mock_jp.find_session_jsonl.assert_not_called()

    def test_jsonl_retry_skips_empty_cwd(self):
        """JSONL retry skips sessions with empty cwd."""
        ctrl = make_controller()
        ctrl.monitor.scan_processes.return_value = {}
        ctrl.session_mgr.find_by_pid.return_value = (None, None)

        ctrl.session_mgr.sessions = {
            'pid-200': _session(
                convo_id='pid-200', pid='200', jsonl='', cwd='',
            ),
        }

        with patch('claudewatch.controller.JsonlParser') as mock_jp:
            result = ctrl.poll_new_processes()

        assert result is False
        mock_jp.find_session_jsonl.assert_not_called()

    def test_no_cwd_uses_empty_string(self):
        """When process cwd is None, it is treated as empty string."""
        ctrl = make_controller()
        ctrl.session_mgr.find_by_pid.return_value = (None, None)

        ctrl.monitor.scan_processes.return_value = {
            '12345': _proc(cwd=None),
        }

        with patch('claudewatch.controller.JsonlParser') as mock_jp, \
             patch('claudewatch.controller.SessionManager') as mock_sm_cls:
            # cwd is None, so find_session_jsonl should NOT be called
            mock_sm_cls.convo_id_for.return_value = 'pid-12345'

            ctrl.poll_new_processes()

        mock_jp.find_session_jsonl.assert_not_called()


# ===========================================================================
# handle_new_session
# ===========================================================================

class TestHandleNewSession:
    def test_watches_jsonl_file(self):
        ctrl = make_controller()
        mock_file_state = MagicMock()
        mock_file_state.title = 'My title'
        ctrl.jsonl_watcher.watch_file.return_value = mock_file_state

        meta = _proc()
        ctrl.handle_new_session('12345', meta, '/path/to/session.jsonl', 'convo-1')

        ctrl.jsonl_watcher.watch_file.assert_called_once_with('/path/to/session.jsonl')

    def test_calls_add_session_with_correct_params(self):
        ctrl = make_controller()
        mock_file_state = MagicMock()
        mock_file_state.title = 'My title'
        ctrl.jsonl_watcher.watch_file.return_value = mock_file_state

        meta = _proc(create_time=1000.0, ide='Cursor', cwd='/my/project', tty='/dev/ttys003')
        ctrl.handle_new_session('12345', meta, '/path/to/session.jsonl', 'convo-1')

        ctrl.session_mgr.add_session.assert_called_once_with(
            convo_id='convo-1',
            pid='12345',
            title='My title',
            create_time=1000.0,
            ide='Cursor',
            cwd='/my/project',
            jsonl_path='/path/to/session.jsonl',
            tty='/dev/ttys003',
        )

    def test_calls_pid_watcher_watch_pid(self):
        ctrl = make_controller()
        ctrl.jsonl_watcher.watch_file.return_value = None

        meta = _proc()
        ctrl.handle_new_session('12345', meta, None, 'convo-1')

        ctrl.pid_watcher.watch_pid.assert_called_once_with(12345)

    def test_sends_notification(self):
        ctrl = make_controller()
        mock_file_state = MagicMock()
        mock_file_state.title = 'Build the feature'
        ctrl.jsonl_watcher.watch_file.return_value = mock_file_state

        meta = _proc(ide='VS Code')
        ctrl.handle_new_session('12345', meta, '/path/to/session.jsonl', 'convo-1')

        ctrl.notifier.notify.assert_called_once_with(
            'New session in VS Code',
            'Build the feature',
            '12345',
        )

    def test_notification_uses_new_conversation_when_no_title(self):
        ctrl = make_controller()
        ctrl.jsonl_watcher.watch_file.return_value = None

        meta = _proc(ide='Terminal')
        ctrl.handle_new_session('12345', meta, None, 'convo-1')

        ctrl.notifier.notify.assert_called_once_with(
            'New session in Terminal',
            'New conversation',
            '12345',
        )

    def test_handles_none_jsonl_path(self):
        ctrl = make_controller()

        meta = _proc()
        ctrl.handle_new_session('12345', meta, None, 'convo-1')

        # Should not call watch_file when jsonl_path is None
        ctrl.jsonl_watcher.watch_file.assert_not_called()
        # add_session should still be called
        ctrl.session_mgr.add_session.assert_called_once()
        assert ctrl.session_mgr.add_session.call_args.kwargs['jsonl_path'] is None

    def test_uses_file_state_title_when_available(self):
        ctrl = make_controller()
        mock_file_state = MagicMock()
        mock_file_state.title = 'Extracted title from JSONL'
        ctrl.jsonl_watcher.watch_file.return_value = mock_file_state

        meta = _proc()
        ctrl.handle_new_session('12345', meta, '/path.jsonl', 'convo-1')

        assert ctrl.session_mgr.add_session.call_args.kwargs['title'] == 'Extracted title from JSONL'

    def test_title_none_when_file_state_is_none(self):
        ctrl = make_controller()
        ctrl.jsonl_watcher.watch_file.return_value = None

        meta = _proc()
        ctrl.handle_new_session('12345', meta, '/path.jsonl', 'convo-1')

        assert ctrl.session_mgr.add_session.call_args.kwargs['title'] is None

    def test_title_none_when_file_state_has_no_title(self):
        ctrl = make_controller()
        mock_file_state = MagicMock()
        mock_file_state.title = None
        ctrl.jsonl_watcher.watch_file.return_value = mock_file_state

        meta = _proc()
        ctrl.handle_new_session('12345', meta, '/path.jsonl', 'convo-1')

        assert ctrl.session_mgr.add_session.call_args.kwargs['title'] is None

    def test_truncates_long_title_in_notification(self):
        ctrl = make_controller()
        long_title = 'x' * 200
        mock_file_state = MagicMock()
        mock_file_state.title = long_title
        ctrl.jsonl_watcher.watch_file.return_value = mock_file_state

        meta = _proc(ide='Cursor')
        ctrl.handle_new_session('12345', meta, '/path.jsonl', 'convo-1')

        # Notification body is truncated to 100 chars
        notify_call = ctrl.notifier.notify.call_args
        assert len(notify_call[0][1]) == 100


# ===========================================================================
# handle_pid_exit
# ===========================================================================

class TestHandlePidExit:
    def test_returns_true_and_completes_session(self):
        ctrl = make_controller()
        session = _session(pid='12345', jsonl='/tmp/test.jsonl')
        ctrl.session_mgr.find_by_pid.return_value = ('convo-1', session)

        result = ctrl.handle_pid_exit(12345)

        assert result is True
        ctrl.session_mgr.complete_session.assert_called_once_with('convo-1')

    def test_unwatches_jsonl_file(self):
        ctrl = make_controller()
        session = _session(pid='12345', jsonl='/tmp/test.jsonl')
        ctrl.session_mgr.find_by_pid.return_value = ('convo-1', session)

        ctrl.handle_pid_exit(12345)

        ctrl.jsonl_watcher.unwatch_file.assert_called_once_with('/tmp/test.jsonl')

    def test_skips_unwatch_when_no_jsonl(self):
        ctrl = make_controller()
        session = _session(pid='12345', jsonl='')
        ctrl.session_mgr.find_by_pid.return_value = ('convo-1', session)

        ctrl.handle_pid_exit(12345)

        ctrl.jsonl_watcher.unwatch_file.assert_not_called()

    def test_sends_completion_notification_when_not_already_notified(self):
        ctrl = make_controller()
        session = _session(pid='12345', title='My task', notified=False)
        ctrl.session_mgr.find_by_pid.return_value = ('convo-1', session)

        ctrl.handle_pid_exit(12345)

        ctrl.notifier.notify.assert_called_once_with(
            'Session completed',
            'My task',
            '12345',
        )

    def test_skips_notification_when_already_notified(self):
        ctrl = make_controller()
        session = _session(pid='12345', title='My task', notified=True)
        ctrl.session_mgr.find_by_pid.return_value = ('convo-1', session)

        ctrl.handle_pid_exit(12345)

        ctrl.notifier.notify.assert_not_called()

    def test_returns_false_for_unknown_pid(self):
        ctrl = make_controller()
        ctrl.session_mgr.find_by_pid.return_value = (None, None)

        result = ctrl.handle_pid_exit(99999)

        assert result is False
        ctrl.session_mgr.complete_session.assert_not_called()
        ctrl.notifier.notify.assert_not_called()

    def test_converts_pid_to_string_for_lookup(self):
        ctrl = make_controller()
        ctrl.session_mgr.find_by_pid.return_value = (None, None)

        ctrl.handle_pid_exit(12345)

        ctrl.session_mgr.find_by_pid.assert_called_once_with('12345')

    def test_truncates_long_title_in_notification(self):
        ctrl = make_controller()
        long_title = 'A' * 200
        session = _session(pid='12345', title=long_title, notified=False)
        ctrl.session_mgr.find_by_pid.return_value = ('convo-1', session)

        ctrl.handle_pid_exit(12345)

        notify_call = ctrl.notifier.notify.call_args
        assert len(notify_call[0][1]) == 100


# ===========================================================================
# handle_jsonl_change
# ===========================================================================

class TestHandleJsonlChange:
    def test_updates_title_when_changed(self):
        ctrl = make_controller()
        session = _session(title='Old title')
        ctrl.session_mgr.find_by_jsonl.return_value = ('convo-1', session)

        file_state = MagicMock()
        file_state.title = 'New title'
        file_state.state = 'active'
        file_state.latest_response = None

        result = ctrl.handle_jsonl_change('/tmp/test.jsonl', file_state)

        assert result is True
        assert session['title'] == 'New title'
        ctrl.session_mgr.save_sessions.assert_called()

    def test_no_title_update_when_same(self):
        ctrl = make_controller()
        session = _session(title='Same title')
        ctrl.session_mgr.find_by_jsonl.return_value = ('convo-1', session)

        file_state = MagicMock()
        file_state.title = 'Same title'
        file_state.state = 'active'
        file_state.latest_response = None

        result = ctrl.handle_jsonl_change('/tmp/test.jsonl', file_state)

        assert result is False

    def test_sends_notification_on_waiting_tool_from_active(self):
        ctrl = make_controller()
        ctrl.NOTIFY_DELAY = 0
        session = _session(last_state='active', ide='VS Code', title='Build task')
        ctrl.session_mgr.find_by_jsonl.return_value = ('convo-1', session)
        ctrl.session_mgr.sessions = {'convo-1': session}
        ctrl.focus_mgr.is_session_focused.return_value = False

        file_state = MagicMock()
        file_state.title = 'Build task'
        file_state.state = 'waiting_tool'
        file_state.latest_response = 'I need to run a command'

        result = ctrl.handle_jsonl_change('/tmp/test.jsonl', file_state)
        _flush_notify_timers(ctrl)

        assert result is True
        ctrl.notifier.notify.assert_called_once()
        notify_args = ctrl.notifier.notify.call_args[0]
        assert 'Needs approval' in notify_args[0]
        assert 'VS Code' in notify_args[0]

    def test_sends_notification_on_waiting_input_from_active(self):
        ctrl = make_controller()
        ctrl.NOTIFY_DELAY = 0
        session = _session(last_state='active', ide='Cursor', title='Debug issue')
        ctrl.session_mgr.find_by_jsonl.return_value = ('convo-1', session)
        ctrl.session_mgr.sessions = {'convo-1': session}
        ctrl.focus_mgr.is_session_focused.return_value = False

        file_state = MagicMock()
        file_state.title = 'Debug issue'
        file_state.state = 'waiting_input'
        file_state.latest_response = 'What should I do next?'

        result = ctrl.handle_jsonl_change('/tmp/test.jsonl', file_state)
        _flush_notify_timers(ctrl)

        assert result is True
        ctrl.notifier.notify.assert_called_once()
        notify_args = ctrl.notifier.notify.call_args[0]
        assert 'Waiting for input' in notify_args[0]
        assert 'Cursor' in notify_args[0]

    def test_suppresses_notification_when_focused(self):
        ctrl = make_controller()
        ctrl.NOTIFY_DELAY = 0
        session = _session(last_state='active', ide='VS Code')
        ctrl.session_mgr.find_by_jsonl.return_value = ('convo-1', session)
        ctrl.session_mgr.sessions = {'convo-1': session}
        ctrl.focus_mgr.is_session_focused.return_value = True

        file_state = MagicMock()
        file_state.title = 'Task'
        file_state.state = 'waiting_tool'
        file_state.latest_response = 'Response'

        ctrl.handle_jsonl_change('/tmp/test.jsonl', file_state)
        _flush_notify_timers(ctrl)

        ctrl.notifier.notify.assert_not_called()

    def test_no_notification_on_active_to_active(self):
        ctrl = make_controller()
        session = _session(last_state='active')
        ctrl.session_mgr.find_by_jsonl.return_value = ('convo-1', session)

        file_state = MagicMock()
        file_state.title = None
        file_state.state = 'active'
        file_state.latest_response = None

        result = ctrl.handle_jsonl_change('/tmp/test.jsonl', file_state)

        assert result is False
        ctrl.notifier.notify.assert_not_called()

    def test_no_notification_on_waiting_tool_from_non_active(self):
        """Notification only fires when transitioning from 'active' state."""
        ctrl = make_controller()
        session = _session(last_state='waiting_input')
        ctrl.session_mgr.find_by_jsonl.return_value = ('convo-1', session)
        ctrl.focus_mgr.is_session_focused.return_value = False

        file_state = MagicMock()
        file_state.title = None
        file_state.state = 'waiting_tool'
        file_state.latest_response = None

        ctrl.handle_jsonl_change('/tmp/test.jsonl', file_state)

        ctrl.notifier.notify.assert_not_called()

    def test_notification_cancelled_when_state_returns_to_active(self):
        """If state goes active→waiting→active before the timer fires,
        the notification should be cancelled."""
        ctrl = make_controller()
        ctrl.NOTIFY_DELAY = 10  # long delay so timer won't fire naturally
        session = _session(last_state='active', ide='VS Code', title='Task')
        ctrl.session_mgr.find_by_jsonl.return_value = ('convo-1', session)
        ctrl.session_mgr.sessions = {'convo-1': session}
        ctrl.focus_mgr.is_session_focused.return_value = False

        # Transition to waiting_tool — schedules a notification
        fs1 = MagicMock()
        fs1.title = 'Task'
        fs1.state = 'waiting_tool'
        fs1.latest_response = 'Need approval'
        ctrl.handle_jsonl_change('/tmp/test.jsonl', fs1)
        assert 'convo-1' in ctrl._notify_timers

        # State returns to active — should cancel the timer
        fs2 = MagicMock()
        fs2.title = 'Task'
        fs2.state = 'active'
        fs2.latest_response = None
        ctrl.handle_jsonl_change('/tmp/test.jsonl', fs2)
        assert 'convo-1' not in ctrl._notify_timers

        ctrl.notifier.notify.assert_not_called()

    def test_updates_latest_response(self):
        ctrl = make_controller()
        session = _session()
        ctrl.session_mgr.find_by_jsonl.return_value = ('convo-1', session)

        file_state = MagicMock()
        file_state.title = None
        file_state.state = 'active'
        file_state.latest_response = 'Here is the updated code'

        result = ctrl.handle_jsonl_change('/tmp/test.jsonl', file_state)

        assert result is True
        assert session['latest_response'] == 'Here is the updated code'
        ctrl.session_mgr.save_sessions.assert_called()

    def test_returns_false_for_unknown_path(self):
        ctrl = make_controller()
        ctrl.session_mgr.find_by_jsonl.return_value = (None, None)

        file_state = MagicMock()
        file_state.title = 'Title'
        file_state.state = 'active'
        file_state.latest_response = 'Response'

        result = ctrl.handle_jsonl_change('/unknown/path.jsonl', file_state)

        assert result is False
        ctrl.session_mgr.save_sessions.assert_not_called()

    def test_returns_false_when_nothing_changed(self):
        ctrl = make_controller()
        session = _session(title='Same', last_state='active')
        ctrl.session_mgr.find_by_jsonl.return_value = ('convo-1', session)

        file_state = MagicMock()
        file_state.title = 'Same'
        file_state.state = 'active'
        file_state.latest_response = None

        result = ctrl.handle_jsonl_change('/tmp/test.jsonl', file_state)

        assert result is False
        ctrl.session_mgr.save_sessions.assert_not_called()

    def test_unknown_state_is_ignored_for_state_transition(self):
        """When new_state is 'unknown', no state transition should occur."""
        ctrl = make_controller()
        session = _session(last_state='active')
        ctrl.session_mgr.find_by_jsonl.return_value = ('convo-1', session)

        file_state = MagicMock()
        file_state.title = None
        file_state.state = 'unknown'
        file_state.latest_response = None

        result = ctrl.handle_jsonl_change('/tmp/test.jsonl', file_state)

        assert result is False
        assert session['last_state'] == 'active'

    def test_notification_body_from_latest_response(self):
        """Notification body is derived from file_state.latest_response."""
        ctrl = make_controller()
        ctrl.NOTIFY_DELAY = 0
        session = _session(last_state='active', ide='Terminal', pid='999')
        ctrl.session_mgr.find_by_jsonl.return_value = ('convo-1', session)
        ctrl.session_mgr.sessions = {'convo-1': session}
        ctrl.focus_mgr.is_session_focused.return_value = False

        file_state = MagicMock()
        file_state.title = 'My task'
        file_state.state = 'waiting_input'
        file_state.latest_response = 'Line1\nLine2\nLine3'

        ctrl.handle_jsonl_change('/tmp/test.jsonl', file_state)
        _flush_notify_timers(ctrl)

        notify_call = ctrl.notifier.notify.call_args
        body = notify_call[0][3]  # 4th positional arg
        assert '\n' not in body  # newlines replaced
        assert 'Line1' in body

    def test_notification_body_truncated_to_150_chars(self):
        ctrl = make_controller()
        ctrl.NOTIFY_DELAY = 0
        session = _session(last_state='active', ide='VS Code')
        ctrl.session_mgr.find_by_jsonl.return_value = ('convo-1', session)
        ctrl.session_mgr.sessions = {'convo-1': session}
        ctrl.focus_mgr.is_session_focused.return_value = False

        file_state = MagicMock()
        file_state.title = 'Task'
        file_state.state = 'waiting_tool'
        file_state.latest_response = 'x' * 300

        ctrl.handle_jsonl_change('/tmp/test.jsonl', file_state)
        _flush_notify_timers(ctrl)

        notify_call = ctrl.notifier.notify.call_args
        body = notify_call[0][3]
        assert len(body) <= 150


# ===========================================================================
# handle_notification_click
# ===========================================================================

class TestHandleNotificationClick:
    def test_focuses_session_for_known_pid(self):
        ctrl = make_controller()
        session = _session(pid='12345')
        ctrl.session_mgr.find_by_pid.return_value = ('convo-1', session)

        ctrl.handle_notification_click({'pid': '12345'})

        ctrl.focus_mgr.focus_session.assert_called_once_with(session)

    def test_noop_for_unknown_pid(self):
        ctrl = make_controller()
        ctrl.session_mgr.find_by_pid.return_value = (None, None)

        ctrl.handle_notification_click({'pid': '99999'})

        ctrl.focus_mgr.focus_session.assert_not_called()

    def test_noop_for_none_info(self):
        ctrl = make_controller()

        ctrl.handle_notification_click(None)

        ctrl.focus_mgr.focus_session.assert_not_called()
        ctrl.session_mgr.find_by_pid.assert_not_called()

    def test_noop_when_info_has_no_pid(self):
        ctrl = make_controller()

        ctrl.handle_notification_click({'something': 'else'})

        ctrl.focus_mgr.focus_session.assert_not_called()
        ctrl.session_mgr.find_by_pid.assert_not_called()

    def test_converts_pid_to_string_for_lookup(self):
        ctrl = make_controller()
        session = _session(pid='12345')
        ctrl.session_mgr.find_by_pid.return_value = ('convo-1', session)

        ctrl.handle_notification_click({'pid': 12345})

        ctrl.session_mgr.find_by_pid.assert_called_once_with('12345')


# ===========================================================================
# get_menu_items
# ===========================================================================

class TestGetMenuItems:
    def test_returns_empty_list_when_no_active(self):
        ctrl = make_controller()
        ctrl.session_mgr.get_active.return_value = []

        assert ctrl.get_menu_items() == []

    def test_returns_items_sorted_by_started_at_descending(self):
        ctrl = make_controller()
        now = time.time()
        sessions = [
            _session(convo_id='old', started_at=now - 600, title='Old', ide='VS Code'),
            _session(convo_id='new', started_at=now - 60, title='New', ide='Cursor'),
        ]
        ctrl.session_mgr.get_active.return_value = sessions
        ctrl.jsonl_watcher.get_file_state.return_value = None
        ctrl.focus_mgr.get_app_icon.return_value = None

        items = ctrl.get_menu_items()

        assert len(items) == 2
        # Newest first
        assert 'New' in items[0]['label']
        assert 'Old' in items[1]['label']

    def test_truncates_long_titles_to_40_chars(self):
        ctrl = make_controller()
        long_title = 'A' * 60
        sessions = [
            _session(title=long_title, started_at=time.time() - 100, ide='Terminal'),
        ]
        ctrl.session_mgr.get_active.return_value = sessions
        ctrl.jsonl_watcher.get_file_state.return_value = None
        ctrl.focus_mgr.get_app_icon.return_value = None

        items = ctrl.get_menu_items()

        # The title in the label should be truncated to 40 + '...'
        assert ('A' * 40 + '...') in items[0]['label']

    def test_deduplicates_menu_keys_with_counter(self):
        ctrl = make_controller()
        now = time.time()
        # Two sessions that produce the same base_label
        sessions = [
            _session(convo_id='s1', title='Same', ide='VS Code', started_at=now - 100),
            _session(convo_id='s2', title='Same', ide='VS Code', started_at=now - 100),
        ]
        ctrl.session_mgr.get_active.return_value = sessions
        ctrl.jsonl_watcher.get_file_state.return_value = None
        ctrl.focus_mgr.get_app_icon.return_value = None

        items = ctrl.get_menu_items()

        title_keys = [i['title_key'] for i in items]
        # First gets no suffix, second gets #1
        assert any('#1' in k for k in title_keys)
        # All keys should be unique
        assert len(set(title_keys)) == len(title_keys)

    def test_includes_icon_path(self):
        ctrl = make_controller()
        sessions = [
            _session(ide='VS Code', started_at=time.time() - 100),
        ]
        ctrl.session_mgr.get_active.return_value = sessions
        ctrl.jsonl_watcher.get_file_state.return_value = None
        ctrl.focus_mgr.get_app_icon.return_value = '/path/to/icon.icns'

        items = ctrl.get_menu_items()

        assert items[0]['icon_path'] == '/path/to/icon.icns'
        ctrl.focus_mgr.get_app_icon.assert_called_with('VS Code')

    def test_msg_text_from_latest_response_in_session(self):
        ctrl = make_controller()
        sessions = [
            _session(
                started_at=time.time() - 100,
                latest_response='Here is the result\nSecond line',
            ),
        ]
        ctrl.session_mgr.get_active.return_value = sessions
        ctrl.focus_mgr.get_app_icon.return_value = None

        items = ctrl.get_menu_items()

        # Newlines replaced, truncated to 70
        assert '\n' not in items[0]['msg_text']
        assert 'Here is the result' in items[0]['msg_text']

    def test_msg_text_from_file_state_when_no_latest_response(self):
        ctrl = make_controller()
        sessions = [
            _session(started_at=time.time() - 100, jsonl='/tmp/test.jsonl'),
        ]
        # Ensure no 'latest_response' key in session
        sessions[0].pop('latest_response', None)
        ctrl.session_mgr.get_active.return_value = sessions

        mock_file_state = MagicMock()
        mock_file_state.latest_response = 'Response from file state'
        ctrl.jsonl_watcher.get_file_state.return_value = mock_file_state
        ctrl.focus_mgr.get_app_icon.return_value = None

        items = ctrl.get_menu_items()

        assert 'Response from file state' in items[0]['msg_text']

    def test_msg_text_default_waiting_for_response(self):
        ctrl = make_controller()
        sessions = [
            _session(started_at=time.time() - 100, jsonl='/tmp/test.jsonl'),
        ]
        ctrl.session_mgr.get_active.return_value = sessions
        ctrl.jsonl_watcher.get_file_state.return_value = None
        ctrl.focus_mgr.get_app_icon.return_value = None

        items = ctrl.get_menu_items()

        assert items[0]['msg_text'] == 'Waiting for response...'

    def test_msg_text_truncated_to_70_chars(self):
        ctrl = make_controller()
        sessions = [
            _session(
                started_at=time.time() - 100,
                latest_response='x' * 200,
            ),
        ]
        ctrl.session_mgr.get_active.return_value = sessions
        ctrl.focus_mgr.get_app_icon.return_value = None

        items = ctrl.get_menu_items()

        assert len(items[0]['msg_text']) == 70

    def test_item_contains_session_reference(self):
        ctrl = make_controller()
        session = _session(started_at=time.time() - 100)
        ctrl.session_mgr.get_active.return_value = [session]
        ctrl.jsonl_watcher.get_file_state.return_value = None
        ctrl.focus_mgr.get_app_icon.return_value = None

        items = ctrl.get_menu_items()

        assert items[0]['session'] is session

    def test_label_includes_ide_title_and_runtime(self):
        ctrl = make_controller()
        sessions = [
            _session(ide='Cursor', title='Fix bug', started_at=time.time() - 120),
        ]
        ctrl.session_mgr.get_active.return_value = sessions
        ctrl.jsonl_watcher.get_file_state.return_value = None
        ctrl.focus_mgr.get_app_icon.return_value = None

        items = ctrl.get_menu_items()

        label = items[0]['label']
        assert 'Cursor' in label
        assert 'Fix bug' in label
        assert '2m' in label


# ===========================================================================
# get_title_badge
# ===========================================================================

class TestGetTitleBadge:
    def test_returns_count_when_active_sessions(self):
        ctrl = make_controller()
        ctrl.session_mgr.get_active.return_value = [_session(), _session()]

        assert ctrl.get_title_badge() == ' 2'

    def test_returns_empty_when_no_active(self):
        ctrl = make_controller()
        ctrl.session_mgr.get_active.return_value = []

        assert ctrl.get_title_badge() == ''

    def test_single_active_session(self):
        ctrl = make_controller()
        ctrl.session_mgr.get_active.return_value = [_session()]

        assert ctrl.get_title_badge() == ' 1'


# ===========================================================================
# paused state
# ===========================================================================

class TestPausedState:
    def test_initially_not_paused(self):
        ctrl = make_controller()
        assert ctrl._paused is False

    def test_can_be_paused(self):
        ctrl = make_controller()
        ctrl._paused = True
        ctrl.monitor.scan_processes.return_value = {'1': _proc()}

        result = ctrl.poll_new_processes()

        assert result is False
        ctrl.monitor.scan_processes.assert_not_called()
