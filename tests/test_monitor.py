"""Tests for claudewatch.monitor — ProcessMonitor."""

import time
from unittest.mock import MagicMock, patch

import psutil
import pytest

from claudewatch.monitor import ProcessMonitor
from tests.conftest import mock_proc_info


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mock_proc(name, parent=None, pid=100):
    """Create a mock psutil.Process-like object for ancestor-chain tests."""
    proc = MagicMock()
    proc.name.return_value = name
    proc.pid = pid
    proc.parent.return_value = parent
    return proc


def _iter_proc(proc_info_dict):
    """Wrap a proc_info dict in a mock that quacks like psutil.process_iter items."""
    p = MagicMock()
    p.info = proc_info_dict
    # parent() returns None by default so detect_parent_ide falls through
    p.parent.return_value = None
    return p


# ===========================================================================
# is_claude_code_process — static / pure, no mocking needed
# ===========================================================================

class TestIsClaudeCodeProcess:
    """ProcessMonitor.is_claude_code_process is a static method that examines
    a proc_info dict and returns True only for genuine Claude Code CLI
    processes.
    """

    def test_absolute_path_to_claude_binary(self):
        info = mock_proc_info(cmdline=['/usr/local/bin/claude'])
        assert ProcessMonitor.is_claude_code_process(info) is True

    def test_claude_code_basename(self):
        info = mock_proc_info(cmdline=['/some/path/claude-code', '--resume'])
        assert ProcessMonitor.is_claude_code_process(info) is True

    def test_bare_claude_name(self):
        info = mock_proc_info(cmdline=['claude'])
        assert ProcessMonitor.is_claude_code_process(info) is True

    def test_desktop_app_rejected(self):
        info = mock_proc_info(
            cmdline=['/Applications/Claude.app/Contents/MacOS/Claude'],
        )
        assert ProcessMonitor.is_claude_code_process(info) is False

    def test_chrome_native_host_rejected(self):
        info = mock_proc_info(
            cmdline=['node', '/path/to/chrome-native-host', '--flag'],
        )
        assert ProcessMonitor.is_claude_code_process(info) is False

    def test_node_without_claude(self):
        info = mock_proc_info(cmdline=['node', '/path/to/something'])
        assert ProcessMonitor.is_claude_code_process(info) is False

    def test_empty_cmdline(self):
        info = {'pid': 1, 'name': 'x', 'cmdline': [], 'create_time': 0}
        assert ProcessMonitor.is_claude_code_process(info) is False

    def test_none_cmdline(self):
        info = {'pid': 1, 'name': 'x', 'cmdline': None, 'create_time': 0}
        assert ProcessMonitor.is_claude_code_process(info) is False

    def test_claude_in_path_but_not_basename(self):
        """'claude' appears in a directory component, not as the executable basename."""
        info = mock_proc_info(cmdline=['/home/claude/node', 'server.js'])
        assert ProcessMonitor.is_claude_code_process(info) is False

    def test_claude_as_argument_not_binary(self):
        """The word 'claude' only appears as a plain argument, not a path basename."""
        info = mock_proc_info(cmdline=['node', 'index.js', '--model', 'claude'])
        # 'claude' by itself IS a valid basename match per the implementation
        assert ProcessMonitor.is_claude_code_process(info) is True

    def test_desktop_app_with_extra_args(self):
        info = mock_proc_info(
            cmdline=['/Applications/Claude.app/Contents/MacOS/Claude', '--some-flag'],
        )
        assert ProcessMonitor.is_claude_code_process(info) is False


# ===========================================================================
# detect_parent_ide — needs mock process ancestor chains
# ===========================================================================

class TestDetectParentIde:
    """detect_parent_ide walks the ancestor process tree and returns a
    human-friendly IDE / terminal label.
    """

    def setup_method(self):
        self.monitor = ProcessMonitor()

    def test_parent_is_vscode_helper(self):
        parent = make_mock_proc('Code Helper', parent=None, pid=50)
        child = make_mock_proc('node', parent=parent, pid=100)
        assert self.monitor.detect_parent_ide(child) == 'VS Code'

    def test_parent_is_cursor_helper(self):
        parent = make_mock_proc('Cursor Helper', parent=None, pid=50)
        child = make_mock_proc('node', parent=parent, pid=100)
        assert self.monitor.detect_parent_ide(child) == 'Cursor'

    def test_grandparent_is_iterm(self):
        grandparent = make_mock_proc('iTerm2', parent=None, pid=10)
        parent = make_mock_proc('zsh', parent=grandparent, pid=50)
        child = make_mock_proc('node', parent=parent, pid=100)
        assert self.monitor.detect_parent_ide(child) == 'iTerm'

    def test_no_matching_ancestor_returns_terminal(self):
        # Build a chain that ends at pid=1 (init/launchd)
        init = make_mock_proc('launchd', parent=None, pid=1)
        mid = make_mock_proc('zsh', parent=init, pid=50)
        child = make_mock_proc('node', parent=mid, pid=100)
        assert self.monitor.detect_parent_ide(child) == 'Terminal'

    def test_no_parent_returns_terminal(self):
        child = make_mock_proc('node', parent=None, pid=100)
        assert self.monitor.detect_parent_ide(child) == 'Terminal'

    def test_nosuchprocess_returns_terminal(self):
        parent = make_mock_proc('Code Helper', parent=None, pid=50)
        child = make_mock_proc('node', parent=parent, pid=100)
        # Make the first parent() call raise
        child.parent.side_effect = psutil.NoSuchProcess(pid=100)
        assert self.monitor.detect_parent_ide(child) == 'Terminal'

    def test_accessdenied_returns_terminal(self):
        parent = make_mock_proc('Code Helper', parent=None, pid=50)
        child = make_mock_proc('node', parent=parent, pid=100)
        child.parent.side_effect = psutil.AccessDenied(pid=100)
        assert self.monitor.detect_parent_ide(child) == 'Terminal'

    def test_ancestor_name_is_case_insensitive(self):
        """IDE_PATTERNS keys are lowercase; the method lowercases proc names."""
        parent = make_mock_proc('CODE HELPER', parent=None, pid=50)
        child = make_mock_proc('node', parent=parent, pid=100)
        assert self.monitor.detect_parent_ide(child) == 'VS Code'

    def test_rubymine_detected(self):
        parent = make_mock_proc('rubymine', parent=None, pid=50)
        child = make_mock_proc('node', parent=parent, pid=100)
        assert self.monitor.detect_parent_ide(child) == 'RubyMine'

    def test_warp_detected(self):
        parent = make_mock_proc('warp', parent=None, pid=50)
        child = make_mock_proc('node', parent=parent, pid=100)
        assert self.monitor.detect_parent_ide(child) == 'Warp'


# ===========================================================================
# scan_processes — needs mock psutil.process_iter
# ===========================================================================

class TestScanProcesses:
    """scan_processes iterates over all system processes, filters for Claude
    Code CLIs, and assembles metadata dicts.
    """

    def setup_method(self):
        self.monitor = ProcessMonitor()

    @patch('claudewatch.monitor.psutil.Process')
    @patch('claudewatch.monitor.psutil.process_iter')
    def test_returns_claude_processes(self, mock_iter, mock_process_cls):
        now = time.time()
        claude_info = mock_proc_info(
            pid=1001, name='node',
            cmdline=['/usr/local/bin/claude', '--resume'],
            create_time=now,
        )
        claude_proc = _iter_proc(claude_info)

        mock_iter.return_value = [claude_proc]

        # Mock psutil.Process(pid) for terminal() and cwd()
        mock_ps_instance = MagicMock()
        mock_ps_instance.terminal.return_value = '/dev/ttys003'
        mock_ps_instance.cwd.return_value = '/home/user/project'
        mock_process_cls.return_value = mock_ps_instance

        results = self.monitor.scan_processes()

        assert '1001' in results
        entry = results['1001']
        assert entry['cmdline'] == ['/usr/local/bin/claude', '--resume']
        assert entry['create_time'] == now
        assert entry['cwd'] == '/home/user/project'
        assert entry['tty'] == '/dev/ttys003'

    @patch('claudewatch.monitor.psutil.Process')
    @patch('claudewatch.monitor.psutil.process_iter')
    def test_skips_non_claude_processes(self, mock_iter, mock_process_cls):
        non_claude = _iter_proc(
            mock_proc_info(pid=2000, name='node', cmdline=['node', 'server.js']),
        )
        mock_iter.return_value = [non_claude]

        results = self.monitor.scan_processes()
        assert results == {}

    @patch('claudewatch.monitor.psutil.process_iter')
    def test_handles_nosuchprocess_during_iteration(self, mock_iter):
        """If a process vanishes mid-iteration, scan_processes skips it."""
        # Build a proc whose info dict access works, but whose cmdline
        # passes is_claude_code_process. Then make the proc's parent()
        # call (used later) raise NoSuchProcess to trigger the outer except.
        # Simpler: use a PropertyMock so that accessing proc.info raises.
        error_proc = MagicMock()
        type(error_proc).info = property(
            lambda self: (_ for _ in ()).throw(psutil.NoSuchProcess(pid=9999)),
        )

        mock_iter.return_value = [error_proc]

        results = self.monitor.scan_processes()
        assert results == {}

    @patch('claudewatch.monitor.psutil.Process')
    @patch('claudewatch.monitor.psutil.process_iter')
    def test_handles_accessdenied_on_terminal(self, mock_iter, mock_process_cls):
        """AccessDenied when reading terminal() should still include the process."""
        claude_info = mock_proc_info(pid=3000, cmdline=['/usr/local/bin/claude'])
        claude_proc = _iter_proc(claude_info)

        mock_iter.return_value = [claude_proc]

        mock_ps = MagicMock()
        mock_ps.terminal.side_effect = psutil.AccessDenied(pid=3000)
        mock_ps.cwd.return_value = '/tmp'
        mock_process_cls.return_value = mock_ps

        results = self.monitor.scan_processes()
        assert '3000' in results
        assert results['3000']['tty'] is None

    @patch('claudewatch.monitor.psutil.Process')
    @patch('claudewatch.monitor.psutil.process_iter')
    def test_multiple_claude_processes(self, mock_iter, mock_process_cls):
        """scan_processes should return all matching Claude processes."""
        proc_a = _iter_proc(mock_proc_info(pid=100, cmdline=['/usr/local/bin/claude']))
        proc_b = _iter_proc(mock_proc_info(pid=200, cmdline=['/opt/bin/claude-code']))
        proc_other = _iter_proc(mock_proc_info(pid=300, cmdline=['node', 'app.js']))

        mock_iter.return_value = [proc_a, proc_b, proc_other]

        mock_ps = MagicMock()
        mock_ps.terminal.return_value = None
        mock_ps.cwd.return_value = '/tmp'
        mock_process_cls.return_value = mock_ps

        results = self.monitor.scan_processes()
        assert '100' in results
        assert '200' in results
        assert '300' not in results

    @patch('claudewatch.monitor.psutil.Process')
    @patch('claudewatch.monitor.psutil.process_iter')
    def test_detect_parent_ide_called_per_process(self, mock_iter, mock_process_cls):
        """Each discovered process should have its IDE detected."""
        vscode_parent = make_mock_proc('Code Helper', parent=None, pid=10)
        claude_proc = _iter_proc(mock_proc_info(pid=500, cmdline=['/usr/local/bin/claude']))
        claude_proc.parent.return_value = vscode_parent

        mock_iter.return_value = [claude_proc]

        mock_ps = MagicMock()
        mock_ps.terminal.return_value = '/dev/ttys001'
        mock_ps.cwd.return_value = '/home/user/project'
        mock_process_cls.return_value = mock_ps

        results = self.monitor.scan_processes()
        assert results['500']['ide'] == 'VS Code'


# ===========================================================================
# _get_session_cwd — static helper
# ===========================================================================

class TestGetSessionCwd:
    """_get_session_cwd wraps psutil.Process(pid).cwd() with error handling."""

    @patch('claudewatch.monitor.psutil.Process')
    def test_returns_cwd(self, mock_process_cls):
        mock_process_cls.return_value.cwd.return_value = '/home/user/project'
        result = ProcessMonitor._get_session_cwd('1234')
        mock_process_cls.assert_called_with(1234)
        assert result == '/home/user/project'

    @patch('claudewatch.monitor.psutil.Process')
    def test_returns_none_on_nosuchprocess(self, mock_process_cls):
        mock_process_cls.side_effect = psutil.NoSuchProcess(pid=9999)
        assert ProcessMonitor._get_session_cwd('9999') is None

    @patch('claudewatch.monitor.psutil.Process')
    def test_returns_none_on_accessdenied(self, mock_process_cls):
        mock_process_cls.side_effect = psutil.AccessDenied(pid=9999)
        assert ProcessMonitor._get_session_cwd('9999') is None
