"""Shared fixtures for ClaudeWatch tests."""

import json
import time

import pytest


@pytest.fixture
def sample_session():
    """Factory for session dicts with sensible defaults."""
    def _make(**overrides):
        defaults = {
            'convo_id': 'test-uuid-1234',
            'pid': '12345',
            'title': 'Test conversation',
            'started_at': time.time() - 300,
            'status': 'running',
            'ide': 'VS Code',
            'cwd': '/tmp/test-project',
            'jsonl': '/tmp/test.jsonl',
            'tty': '/dev/ttys001',
            'notified': False,
            'last_state': 'active',
        }
        defaults.update(overrides)
        return defaults
    return _make


@pytest.fixture
def write_jsonl(tmp_path):
    """Write JSONL entries to a temp file, return the path."""
    def _write(entries, filename='session.jsonl'):
        path = tmp_path / filename
        with open(path, 'w') as f:
            for entry in entries:
                f.write(json.dumps(entry) + '\n')
        return path
    return _write


@pytest.fixture
def session_mgr(tmp_path):
    """SessionManager with data_dir pointed at tmp_path."""
    from claudewatch.session import SessionManager
    return SessionManager(data_dir=tmp_path)


def make_user_entry(text):
    """Create a JSONL user message entry."""
    return {
        'type': 'user',
        'message': {
            'role': 'user',
            'content': [{'type': 'text', 'text': text}],
        },
    }


def make_assistant_entry(blocks):
    """Create a JSONL assistant message entry.

    blocks: list of dicts like [{'type': 'text', 'text': '...'}]
    """
    return {
        'type': 'assistant',
        'message': {
            'role': 'assistant',
            'content': blocks,
        },
    }


def make_tool_use_block(name='Read', tool_id='tool_1'):
    return {'type': 'tool_use', 'id': tool_id, 'name': name, 'input': {}}


def make_text_block(text):
    return {'type': 'text', 'text': text}


def make_thinking_block(text='thinking...'):
    return {'type': 'thinking', 'thinking': text}


def mock_proc_info(pid=1000, name='node', cmdline=None, create_time=None):
    """Create a dict matching psutil proc.info format."""
    return {
        'pid': pid,
        'name': name,
        'cmdline': cmdline or ['/usr/local/bin/claude'],
        'create_time': create_time or time.time(),
    }
