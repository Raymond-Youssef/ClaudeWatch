"""Tests for claudewatch.watcher — JsonlFileState and JsonlWatcher."""

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from claudewatch.watcher import JsonlFileState, JsonlWatcher, _DirectoryHandler
from tests.conftest import (
    make_assistant_entry,
    make_text_block,
    make_thinking_block,
    make_tool_use_block,
    make_user_entry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_entries(path, entries):
    """Append JSONL entries to a file."""
    with open(path, 'a') as f:
        for entry in entries:
            f.write(json.dumps(entry) + '\n')


def _make_progress_entry():
    return {'type': 'progress', 'data': {'percent': 50}}


def _make_system_entry():
    return {'type': 'system', 'message': 'session started'}


# ===========================================================================
# JsonlFileState
# ===========================================================================

class TestJsonlFileStateRefresh:
    """Tests for JsonlFileState.refresh()."""

    def test_returns_false_when_file_unchanged(self, tmp_path):
        path = tmp_path / 'test.jsonl'
        _write_entries(path, [make_user_entry('hello')])

        state = JsonlFileState(path)
        state.refresh()  # initial read

        # Second refresh with no new data
        assert state.refresh() is False

    def test_returns_true_when_new_data_changes_state(self, tmp_path):
        path = tmp_path / 'test.jsonl'
        _write_entries(path, [make_user_entry('hello')])

        state = JsonlFileState(path)
        state.refresh()
        assert state.state == 'active'

        # Append assistant response that changes state
        _write_entries(path, [
            make_assistant_entry([make_text_block('Done!')])
        ])
        assert state.refresh() is True
        assert state.state == 'waiting_input'

    def test_returns_true_when_latest_response_changes(self, tmp_path):
        path = tmp_path / 'test.jsonl'
        _write_entries(path, [
            make_user_entry('hello'),
            make_assistant_entry([make_text_block('response 1')]),
        ])

        state = JsonlFileState(path)
        state.refresh()
        assert state.latest_response == 'response 1'

        # Append new user + assistant pair keeping state the same
        # but changing latest_response
        _write_entries(path, [
            make_user_entry('more'),
            make_assistant_entry([make_text_block('response 2')]),
        ])
        # State goes active -> waiting_input (same as before the append),
        # but latest_response changes from 'response 1' to 'response 2'.
        assert state.refresh() is True
        assert state.latest_response == 'response 2'

    def test_returns_false_on_oserror_stat(self, tmp_path):
        path = tmp_path / 'nonexistent.jsonl'
        state = JsonlFileState(path)
        assert state.refresh() is False

    def test_returns_false_on_oserror_file_deleted_after_stat(self, tmp_path):
        path = tmp_path / 'test.jsonl'
        _write_entries(path, [make_user_entry('hello')])

        state = JsonlFileState(path)
        # First refresh reads the file
        state.refresh()

        # Append more data so size > last_offset
        _write_entries(path, [make_user_entry('more')])

        # Delete file after stat would succeed but before open
        with patch.object(Path, 'stat', return_value=MagicMock(st_size=99999)):
            with patch('builtins.open', side_effect=OSError('deleted')):
                assert state.refresh() is False

    def test_incremental_reading_only_processes_new_bytes(self, tmp_path):
        path = tmp_path / 'test.jsonl'
        _write_entries(path, [make_user_entry('first')])

        state = JsonlFileState(path)
        state.refresh()
        assert state.state == 'active'
        assert state.title == 'first'
        first_offset = state.last_offset
        assert first_offset > 0

        # Append new entry
        _write_entries(path, [
            make_assistant_entry([make_text_block('reply')])
        ])
        state.refresh()
        # Offset should have advanced
        assert state.last_offset > first_offset
        assert state.state == 'waiting_input'
        assert state.latest_response == 'reply'

    def test_multiple_refreshes_track_offset_correctly(self, tmp_path):
        path = tmp_path / 'test.jsonl'
        _write_entries(path, [make_user_entry('msg1')])

        state = JsonlFileState(path)
        state.refresh()
        offset1 = state.last_offset

        _write_entries(path, [make_user_entry('msg2')])
        state.refresh()
        offset2 = state.last_offset
        assert offset2 > offset1

        _write_entries(path, [
            make_assistant_entry([make_text_block('final')])
        ])
        state.refresh()
        offset3 = state.last_offset
        assert offset3 > offset2

        # No new data: offset stays the same
        state.refresh()
        assert state.last_offset == offset3


class TestJsonlFileStateProcessEntry:
    """Tests for JsonlFileState._process_entry()."""

    def test_user_message_sets_state_active(self):
        state = JsonlFileState('/fake/path.jsonl')
        state._process_entry(make_user_entry('hello'))
        assert state.state == 'active'

    def test_assistant_tool_use_last_block_sets_waiting_tool(self):
        state = JsonlFileState('/fake/path.jsonl')
        entry = make_assistant_entry([
            make_text_block('Let me check'),
            make_tool_use_block('Read'),
        ])
        state._process_entry(entry)
        assert state.state == 'waiting_tool'

    def test_assistant_text_last_block_sets_waiting_input(self):
        state = JsonlFileState('/fake/path.jsonl')
        entry = make_assistant_entry([make_text_block('All done.')])
        state._process_entry(entry)
        assert state.state == 'waiting_input'

    def test_assistant_thinking_last_block_sets_active(self):
        state = JsonlFileState('/fake/path.jsonl')
        entry = make_assistant_entry([make_thinking_block('hmm...')])
        state._process_entry(entry)
        assert state.state == 'active'

    def test_non_message_progress_entry_skipped(self):
        state = JsonlFileState('/fake/path.jsonl')
        state.state = 'waiting_input'
        state._process_entry(_make_progress_entry())
        assert state.state == 'waiting_input'  # unchanged

    def test_non_message_system_entry_skipped(self):
        state = JsonlFileState('/fake/path.jsonl')
        state.state = 'active'
        state._process_entry(_make_system_entry())
        assert state.state == 'active'  # unchanged

    def test_assistant_text_blocks_update_latest_response(self):
        state = JsonlFileState('/fake/path.jsonl')
        entry = make_assistant_entry([
            make_text_block('Hello <b>world</b>'),
        ])
        state._process_entry(entry)
        assert state.latest_response == 'Hello world'

    def test_assistant_strips_xml_tags_from_response(self):
        state = JsonlFileState('/fake/path.jsonl')
        entry = make_assistant_entry([
            make_text_block('<system-reminder>secret</system-reminder>Visible text'),
        ])
        state._process_entry(entry)
        assert 'secret' not in state.latest_response
        assert 'Visible text' in state.latest_response

    def test_multiple_text_blocks_latest_response_gets_last_one(self):
        state = JsonlFileState('/fake/path.jsonl')
        entry = make_assistant_entry([
            make_text_block('first block'),
            make_text_block('second block'),
            make_text_block('third block'),
        ])
        state._process_entry(entry)
        # The for loop iterates through all text blocks sequentially,
        # so latest_response should be the last text block.
        assert state.latest_response == 'third block'

    def test_user_entry_with_no_prior_title_extracts_title(self):
        state = JsonlFileState('/fake/path.jsonl')
        assert state.title is None
        state._process_entry(make_user_entry('My first question'))
        assert state.title == 'My first question'


class TestJsonlFileStateExtractTitle:
    """Tests for JsonlFileState._extract_title()."""

    def test_string_content_extracts_title(self):
        state = JsonlFileState('/fake/path.jsonl')
        state._extract_title('Hello world')
        assert state.title == 'Hello world'

    def test_list_content_with_text_block_extracts_title(self):
        state = JsonlFileState('/fake/path.jsonl')
        state._extract_title([{'type': 'text', 'text': 'List content title'}])
        assert state.title == 'List content title'

    def test_xml_tags_stripped_from_title(self):
        state = JsonlFileState('/fake/path.jsonl')
        state._extract_title('<b>Bold</b> title')
        assert state.title == 'Bold title'

    def test_empty_string_content_does_not_set_title(self):
        state = JsonlFileState('/fake/path.jsonl')
        state._extract_title('')
        assert state.title is None

    def test_empty_list_content_does_not_set_title(self):
        state = JsonlFileState('/fake/path.jsonl')
        state._extract_title([])
        assert state.title is None

    def test_whitespace_only_string_does_not_set_title(self):
        state = JsonlFileState('/fake/path.jsonl')
        state._extract_title('   ')
        # _strip_xml_tags('   ') returns '' which is falsy
        assert state.title is None

    def test_second_user_message_does_not_override_title(self):
        state = JsonlFileState('/fake/path.jsonl')
        state._process_entry(make_user_entry('First title'))
        assert state.title == 'First title'

        state._process_entry(make_user_entry('Second message'))
        # Title should remain 'First title'
        assert state.title == 'First title'

    def test_list_content_with_xml_tags_in_text_block(self):
        state = JsonlFileState('/fake/path.jsonl')
        state._extract_title([
            {'type': 'text', 'text': '<em>Emphasized</em> title text'}
        ])
        assert state.title == 'Emphasized title text'

    def test_list_content_extracts_first_non_empty_text_block(self):
        state = JsonlFileState('/fake/path.jsonl')
        state._extract_title([
            {'type': 'image', 'data': 'base64...'},
            {'type': 'text', 'text': ''},
            {'type': 'text', 'text': 'Actual title'},
        ])
        assert state.title == 'Actual title'


# ===========================================================================
# JsonlWatcher
# ===========================================================================

class TestJsonlWatcherWatchUnwatch:
    """Tests for watch_file / unwatch_file."""

    def test_watch_file_creates_state_and_calls_refresh(self, tmp_path):
        path = tmp_path / 'test.jsonl'
        _write_entries(path, [make_user_entry('hello')])

        mock_observer = MagicMock()
        watcher = JsonlWatcher(on_change_callback=None, observer=mock_observer)

        file_state = watcher.watch_file(str(path))
        assert isinstance(file_state, JsonlFileState)
        # refresh() was called during watch_file, so state should be updated
        assert file_state.state == 'active'
        assert file_state.title == 'hello'

    def test_watch_file_returns_existing_state_for_already_watched(self, tmp_path):
        path = tmp_path / 'test.jsonl'
        _write_entries(path, [make_user_entry('hello')])

        mock_observer = MagicMock()
        watcher = JsonlWatcher(on_change_callback=None, observer=mock_observer)

        state1 = watcher.watch_file(str(path))
        state2 = watcher.watch_file(str(path))
        assert state1 is state2

    def test_watch_file_schedules_observer_for_new_directory(self, tmp_path):
        path = tmp_path / 'test.jsonl'
        _write_entries(path, [make_user_entry('hi')])

        mock_observer = MagicMock()
        watcher = JsonlWatcher(on_change_callback=None, observer=mock_observer)

        watcher.watch_file(str(path))
        mock_observer.schedule.assert_called_once()
        args, kwargs = mock_observer.schedule.call_args
        assert args[1] == str(tmp_path)
        assert kwargs.get('recursive', True) is False

    def test_watch_file_does_not_double_schedule_same_directory(self, tmp_path):
        path1 = tmp_path / 'file1.jsonl'
        path2 = tmp_path / 'file2.jsonl'
        _write_entries(path1, [make_user_entry('a')])
        _write_entries(path2, [make_user_entry('b')])

        mock_observer = MagicMock()
        watcher = JsonlWatcher(on_change_callback=None, observer=mock_observer)

        watcher.watch_file(str(path1))
        watcher.watch_file(str(path2))
        # Only one schedule call for the shared directory
        assert mock_observer.schedule.call_count == 1

    def test_unwatch_file_removes_state_and_pending(self, tmp_path):
        path = tmp_path / 'test.jsonl'
        _write_entries(path, [make_user_entry('hello')])

        mock_observer = MagicMock()
        watcher = JsonlWatcher(on_change_callback=None, observer=mock_observer)

        watcher.watch_file(str(path))
        assert watcher.get_file_state(str(path)) is not None

        # Simulate a pending modification
        watcher._pending_modified[str(path)] = time.monotonic()

        watcher.unwatch_file(str(path))
        assert watcher.get_file_state(str(path)) is None
        assert str(path) not in watcher._pending_modified

    def test_unwatch_file_unschedules_observer_when_no_more_files_in_dir(self, tmp_path):
        path = tmp_path / 'test.jsonl'
        _write_entries(path, [make_user_entry('hello')])

        mock_observer = MagicMock()
        mock_watch = MagicMock()
        mock_observer.schedule.return_value = mock_watch
        watcher = JsonlWatcher(on_change_callback=None, observer=mock_observer)

        watcher.watch_file(str(path))
        watcher.unwatch_file(str(path))
        mock_observer.unschedule.assert_called_once_with(mock_watch)

    def test_unwatch_file_keeps_observer_when_other_files_in_dir(self, tmp_path):
        path1 = tmp_path / 'file1.jsonl'
        path2 = tmp_path / 'file2.jsonl'
        _write_entries(path1, [make_user_entry('a')])
        _write_entries(path2, [make_user_entry('b')])

        mock_observer = MagicMock()
        watcher = JsonlWatcher(on_change_callback=None, observer=mock_observer)

        watcher.watch_file(str(path1))
        watcher.watch_file(str(path2))
        watcher.unwatch_file(str(path1))
        # Observer should NOT be unscheduled because file2 is still watched
        mock_observer.unschedule.assert_not_called()


class TestJsonlWatcherGetFileState:
    """Tests for get_file_state."""

    def test_returns_state_for_watched_path(self, tmp_path):
        path = tmp_path / 'test.jsonl'
        _write_entries(path, [make_user_entry('hello')])

        mock_observer = MagicMock()
        watcher = JsonlWatcher(on_change_callback=None, observer=mock_observer)

        expected = watcher.watch_file(str(path))
        result = watcher.get_file_state(str(path))
        assert result is expected

    def test_returns_none_for_unwatched_path(self):
        mock_observer = MagicMock()
        watcher = JsonlWatcher(on_change_callback=None, observer=mock_observer)
        assert watcher.get_file_state('/does/not/exist.jsonl') is None


class TestJsonlWatcherSeedSessions:
    """Tests for seed_sessions."""

    def test_watches_jsonl_files_from_session_dicts(self, tmp_path):
        path1 = tmp_path / 'session1.jsonl'
        path2 = tmp_path / 'session2.jsonl'
        _write_entries(path1, [make_user_entry('a')])
        _write_entries(path2, [make_user_entry('b')])

        mock_observer = MagicMock()
        watcher = JsonlWatcher(on_change_callback=None, observer=mock_observer)

        sessions = [
            {'jsonl': str(path1), 'convo_id': '1'},
            {'jsonl': str(path2), 'convo_id': '2'},
        ]
        watcher.seed_sessions(sessions)

        assert watcher.get_file_state(str(path1)) is not None
        assert watcher.get_file_state(str(path2)) is not None

    def test_skips_sessions_without_jsonl_key(self, tmp_path):
        path = tmp_path / 'valid.jsonl'
        _write_entries(path, [make_user_entry('a')])

        mock_observer = MagicMock()
        watcher = JsonlWatcher(on_change_callback=None, observer=mock_observer)

        sessions = [
            {'jsonl': str(path), 'convo_id': '1'},
            {'convo_id': '2'},                        # no jsonl key
            {'jsonl': '', 'convo_id': '3'},           # empty jsonl value
        ]
        watcher.seed_sessions(sessions)

        assert watcher.get_file_state(str(path)) is not None
        # The other two sessions should not have created states
        assert len(watcher._file_states) == 1


class TestJsonlWatcherDebounce:
    """Tests for debounce behavior."""

    def test_on_file_modified_schedules_debounced_processing(self, tmp_path):
        path = tmp_path / 'test.jsonl'
        _write_entries(path, [make_user_entry('hello')])

        mock_observer = MagicMock()
        callback = MagicMock()
        watcher = JsonlWatcher(on_change_callback=callback, observer=mock_observer)
        watcher.watch_file(str(path))

        # Simulate file modification event
        watcher._on_file_modified(str(path))

        # Should have a pending entry
        assert str(path) in watcher._pending_modified
        # Should have a debounce timer scheduled
        assert watcher._debounce_timer is not None
        assert watcher._debounce_timer.is_alive()

        # Clean up the timer
        watcher._debounce_timer.cancel()

    def test_on_file_modified_ignores_unwatched_files(self, tmp_path):
        mock_observer = MagicMock()
        watcher = JsonlWatcher(on_change_callback=None, observer=mock_observer)

        watcher._on_file_modified('/not/watched.jsonl')
        assert '/not/watched.jsonl' not in watcher._pending_modified
        assert watcher._debounce_timer is None

    def test_process_pending_calls_refresh_and_invokes_callback_on_change(self, tmp_path):
        path = tmp_path / 'test.jsonl'
        _write_entries(path, [make_user_entry('hello')])

        mock_observer = MagicMock()
        callback = MagicMock()
        watcher = JsonlWatcher(on_change_callback=callback, observer=mock_observer)
        watcher.watch_file(str(path))

        # Append new data so refresh returns True
        _write_entries(path, [
            make_assistant_entry([make_text_block('response!')])
        ])

        # Set up pending entry
        watcher._pending_modified[str(path)] = time.monotonic()

        # Call _process_pending directly
        watcher._process_pending()

        # Callback should have been invoked with path and file_state
        callback.assert_called_once()
        call_args = callback.call_args
        assert call_args[0][0] == str(path)
        assert isinstance(call_args[0][1], JsonlFileState)
        assert call_args[0][1].latest_response == 'response!'

    def test_process_pending_no_callback_when_no_change(self, tmp_path):
        path = tmp_path / 'test.jsonl'
        _write_entries(path, [make_user_entry('hello')])

        mock_observer = MagicMock()
        callback = MagicMock()
        watcher = JsonlWatcher(on_change_callback=callback, observer=mock_observer)
        watcher.watch_file(str(path))

        # No new data appended -- refresh will return False
        watcher._pending_modified[str(path)] = time.monotonic()
        watcher._process_pending()

        callback.assert_not_called()

    def test_process_pending_no_callback_when_callback_is_none(self, tmp_path):
        path = tmp_path / 'test.jsonl'
        _write_entries(path, [make_user_entry('hello')])

        mock_observer = MagicMock()
        watcher = JsonlWatcher(on_change_callback=None, observer=mock_observer)
        watcher.watch_file(str(path))

        _write_entries(path, [
            make_assistant_entry([make_text_block('response')])
        ])
        watcher._pending_modified[str(path)] = time.monotonic()

        # Should not raise even without a callback
        watcher._process_pending()

    def test_process_pending_clears_pending_modified(self, tmp_path):
        path = tmp_path / 'test.jsonl'
        _write_entries(path, [make_user_entry('hello')])

        mock_observer = MagicMock()
        watcher = JsonlWatcher(on_change_callback=None, observer=mock_observer)
        watcher.watch_file(str(path))

        watcher._pending_modified[str(path)] = time.monotonic()
        watcher._process_pending()
        assert len(watcher._pending_modified) == 0

    def test_process_pending_skips_unwatched_pending_entry(self, tmp_path):
        path = tmp_path / 'test.jsonl'
        _write_entries(path, [make_user_entry('hello')])

        mock_observer = MagicMock()
        callback = MagicMock()
        watcher = JsonlWatcher(on_change_callback=callback, observer=mock_observer)
        watcher.watch_file(str(path))

        # Manually add a pending entry for an unwatched file
        watcher._pending_modified['/unwatched/file.jsonl'] = time.monotonic()
        watcher._process_pending()

        # Callback should not be called for the unwatched file
        callback.assert_not_called()

    def test_multiple_on_file_modified_cancels_previous_timer(self, tmp_path):
        path = tmp_path / 'test.jsonl'
        _write_entries(path, [make_user_entry('hello')])

        mock_observer = MagicMock()
        watcher = JsonlWatcher(on_change_callback=None, observer=mock_observer)
        watcher.watch_file(str(path))

        watcher._on_file_modified(str(path))
        first_timer = watcher._debounce_timer

        watcher._on_file_modified(str(path))
        second_timer = watcher._debounce_timer

        # The second call should have created a new timer
        assert second_timer is not first_timer
        # First timer should have been cancelled
        assert not first_timer.is_alive() or first_timer.finished.is_set()

        # Clean up
        second_timer.cancel()


# ===========================================================================
# _DirectoryHandler
# ===========================================================================

class TestDirectoryHandler:
    """Tests for the _DirectoryHandler event forwarding."""

    def test_on_modified_forwards_jsonl_files(self):
        mock_watcher = MagicMock()
        handler = _DirectoryHandler(mock_watcher)

        event = MagicMock()
        event.is_directory = False
        event.src_path = '/some/dir/file.jsonl'

        handler.on_modified(event)
        mock_watcher._on_file_modified.assert_called_once_with('/some/dir/file.jsonl')

    def test_on_modified_ignores_non_jsonl_files(self):
        mock_watcher = MagicMock()
        handler = _DirectoryHandler(mock_watcher)

        event = MagicMock()
        event.is_directory = False
        event.src_path = '/some/dir/file.txt'

        handler.on_modified(event)
        mock_watcher._on_file_modified.assert_not_called()

    def test_on_modified_ignores_directory_events(self):
        mock_watcher = MagicMock()
        handler = _DirectoryHandler(mock_watcher)

        event = MagicMock()
        event.is_directory = True
        event.src_path = '/some/dir/subdir.jsonl'

        handler.on_modified(event)
        mock_watcher._on_file_modified.assert_not_called()
