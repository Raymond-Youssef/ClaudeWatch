"""Tests for claudewatch.focus.FocusManager."""

import subprocess
from unittest.mock import MagicMock, patch, call

import pytest

from claudewatch.focus import FocusManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session(**overrides):
    """Build a minimal session dict with sensible defaults."""
    defaults = {
        'ide': 'VS Code',
        'tty': '/dev/ttys001',
        'cwd': '/tmp/test-project',
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# focus_session — dispatch routing
# ---------------------------------------------------------------------------

class TestFocusSessionDispatch:
    """focus_session routes to the correct internal method."""

    def test_terminal_with_tty_calls_focus_terminal(self):
        fm = FocusManager()
        with patch.object(fm, '_focus_terminal', return_value=True) as mock_term:
            fm.focus_session(_session(ide='Terminal', tty='/dev/ttys001'))
            mock_term.assert_called_once_with('/dev/ttys001')

    def test_iterm_with_tty_calls_focus_iterm(self):
        fm = FocusManager()
        with patch.object(fm, '_focus_iterm', return_value=True) as mock_iterm:
            fm.focus_session(_session(ide='iTerm', tty='/dev/ttys002'))
            mock_iterm.assert_called_once_with('/dev/ttys002')

    def test_vscode_with_cwd_calls_focus_ide_via_uri(self):
        fm = FocusManager()
        with patch.object(fm, '_focus_ide_via_uri', return_value=True) as mock_uri:
            fm.focus_session(_session(ide='VS Code', cwd='/projects/foo', tty=''))
            mock_uri.assert_called_once_with('VS Code', '/projects/foo')

    def test_cursor_with_cwd_calls_focus_ide_via_uri(self):
        fm = FocusManager()
        with patch.object(fm, '_focus_ide_via_uri', return_value=True) as mock_uri:
            fm.focus_session(_session(ide='Cursor', cwd='/projects/bar', tty=''))
            mock_uri.assert_called_once_with('Cursor', '/projects/bar')

    def test_unknown_ide_calls_focus_app(self):
        fm = FocusManager()
        with patch.object(fm, '_focus_app') as mock_app:
            fm.focus_session(_session(ide='SublimeText', tty='', cwd=''))
            mock_app.assert_called_once_with('SublimeText')

    def test_terminal_without_tty_falls_through_to_focus_app(self):
        fm = FocusManager()
        with patch.object(fm, '_focus_terminal') as mock_term, \
             patch.object(fm, '_focus_app') as mock_app:
            fm.focus_session(_session(ide='Terminal', tty=''))
            mock_term.assert_not_called()
            mock_app.assert_called_once_with('Terminal')

    def test_vscode_without_cwd_falls_through_to_focus_app(self):
        fm = FocusManager()
        with patch.object(fm, '_focus_ide_via_uri') as mock_uri, \
             patch.object(fm, '_focus_app') as mock_app:
            fm.focus_session(_session(ide='VS Code', cwd='', tty=''))
            mock_uri.assert_not_called()
            mock_app.assert_called_once_with('Visual Studio Code')

    def test_terminal_focus_failure_falls_through_to_focus_app(self):
        """When _focus_terminal returns False, focus_session should
        continue and try _focus_app as a fallback."""
        fm = FocusManager()
        with patch.object(fm, '_focus_terminal', return_value=False) as mock_term, \
             patch.object(fm, '_focus_app') as mock_app:
            fm.focus_session(_session(ide='Terminal', tty='/dev/ttys001'))
            mock_term.assert_called_once()
            mock_app.assert_called_once_with('Terminal')

    def test_iterm_focus_failure_falls_through_to_focus_app(self):
        fm = FocusManager()
        with patch.object(fm, '_focus_iterm', return_value=False) as mock_iterm, \
             patch.object(fm, '_focus_app') as mock_app:
            fm.focus_session(_session(ide='iTerm', tty='/dev/ttys001'))
            mock_iterm.assert_called_once()
            mock_app.assert_called_once_with('iTerm2')

    def test_ide_uri_failure_falls_through_to_focus_app(self):
        fm = FocusManager()
        with patch.object(fm, '_focus_ide_via_uri', return_value=False) as mock_uri, \
             patch.object(fm, '_focus_app') as mock_app:
            fm.focus_session(_session(ide='VS Code', cwd='/projects/foo', tty=''))
            mock_uri.assert_called_once()
            mock_app.assert_called_once_with('Visual Studio Code')

    def test_tty_is_sanitized(self):
        """Special characters in TTY should be stripped by _SAFE_TTY_RE."""
        fm = FocusManager()
        with patch.object(fm, '_focus_terminal', return_value=True) as mock_term:
            fm.focus_session(_session(ide='Terminal', tty='/dev/ttys001; rm -rf /'))
            # After sanitization: only [a-zA-Z0-9/] remain
            mock_term.assert_called_once_with('/dev/ttys001rmrf/')

    def test_empty_ide_with_no_app_name_does_not_call_focus_app(self):
        """When ide is empty string, APP_NAME_MAP returns '' which is falsy."""
        fm = FocusManager()
        with patch.object(fm, '_focus_app') as mock_app:
            fm.focus_session(_session(ide='', tty='', cwd=''))
            mock_app.assert_not_called()

    def test_known_ide_maps_to_correct_app_name(self):
        """RubyMine, for example, should use the APP_NAME_MAP value."""
        fm = FocusManager()
        with patch.object(fm, '_focus_app') as mock_app:
            fm.focus_session(_session(ide='RubyMine', tty='', cwd=''))
            mock_app.assert_called_once_with('RubyMine')


# ---------------------------------------------------------------------------
# _focus_ide_via_uri
# ---------------------------------------------------------------------------

class TestFocusIdeViaUri:

    @patch('claudewatch.focus.subprocess')
    def test_vscode_uri(self, mock_subprocess):
        fm = FocusManager()
        result = fm._focus_ide_via_uri('VS Code', '/projects/myapp')
        assert result is True
        mock_subprocess.Popen.assert_called_once_with(
            ['open', 'vscode://file/projects/myapp'],
            stdout=mock_subprocess.DEVNULL,
            stderr=mock_subprocess.DEVNULL,
        )

    @patch('claudewatch.focus.subprocess')
    def test_cursor_uri(self, mock_subprocess):
        fm = FocusManager()
        result = fm._focus_ide_via_uri('Cursor', '/home/user/code')
        assert result is True
        mock_subprocess.Popen.assert_called_once_with(
            ['open', 'cursor://file/home/user/code'],
            stdout=mock_subprocess.DEVNULL,
            stderr=mock_subprocess.DEVNULL,
        )

    @patch('claudewatch.focus.subprocess')
    def test_returns_true_on_success(self, mock_subprocess):
        fm = FocusManager()
        assert fm._focus_ide_via_uri('VS Code', '/tmp') is True

    def test_returns_false_for_unknown_ide(self):
        fm = FocusManager()
        result = fm._focus_ide_via_uri('Notepad', '/tmp')
        assert result is False

    @patch('claudewatch.focus.subprocess')
    def test_returns_false_on_exception(self, mock_subprocess):
        mock_subprocess.Popen.side_effect = OSError('open not found')
        mock_subprocess.DEVNULL = subprocess.DEVNULL
        fm = FocusManager()
        result = fm._focus_ide_via_uri('VS Code', '/tmp')
        assert result is False


# ---------------------------------------------------------------------------
# _focus_terminal
# ---------------------------------------------------------------------------

class TestFocusTerminal:

    @patch('claudewatch.focus.subprocess')
    def test_calls_osascript_with_terminal_script(self, mock_subprocess):
        fm = FocusManager()
        result = fm._focus_terminal('/dev/ttys003')
        assert result is True
        mock_subprocess.run.assert_called_once()
        args = mock_subprocess.run.call_args
        cmd = args[0][0]
        assert cmd[0] == 'osascript'
        assert cmd[1] == '-e'
        assert 'Terminal' in cmd[2]
        assert '/dev/ttys003' in cmd[2]
        assert args[1]['timeout'] == 3

    @patch('claudewatch.focus.subprocess')
    def test_returns_true_on_success(self, mock_subprocess):
        fm = FocusManager()
        assert fm._focus_terminal('/dev/ttys001') is True

    @patch('claudewatch.focus.subprocess')
    def test_returns_false_on_exception(self, mock_subprocess):
        mock_subprocess.run.side_effect = subprocess.TimeoutExpired(cmd='osascript', timeout=3)
        fm = FocusManager()
        assert fm._focus_terminal('/dev/ttys001') is False

    @patch('claudewatch.focus.subprocess')
    def test_applescript_contains_tty_matching(self, mock_subprocess):
        fm = FocusManager()
        fm._focus_terminal('/dev/ttys042')
        script = mock_subprocess.run.call_args[0][0][2]
        assert 'tty of t is "/dev/ttys042"' in script

    @patch('claudewatch.focus.subprocess')
    def test_returns_false_on_generic_exception(self, mock_subprocess):
        mock_subprocess.run.side_effect = Exception('something went wrong')
        fm = FocusManager()
        assert fm._focus_terminal('/dev/ttys001') is False


# ---------------------------------------------------------------------------
# _focus_iterm
# ---------------------------------------------------------------------------

class TestFocusIterm:

    @patch('claudewatch.focus.subprocess')
    def test_calls_osascript_with_iterm_script(self, mock_subprocess):
        fm = FocusManager()
        result = fm._focus_iterm('/dev/ttys005')
        assert result is True
        mock_subprocess.run.assert_called_once()
        args = mock_subprocess.run.call_args
        cmd = args[0][0]
        assert cmd[0] == 'osascript'
        assert cmd[1] == '-e'
        assert 'iTerm2' in cmd[2]
        assert '/dev/ttys005' in cmd[2]
        assert args[1]['timeout'] == 3

    @patch('claudewatch.focus.subprocess')
    def test_returns_true_on_success(self, mock_subprocess):
        fm = FocusManager()
        assert fm._focus_iterm('/dev/ttys001') is True

    @patch('claudewatch.focus.subprocess')
    def test_returns_false_on_exception(self, mock_subprocess):
        mock_subprocess.run.side_effect = OSError('osascript not found')
        fm = FocusManager()
        assert fm._focus_iterm('/dev/ttys001') is False

    @patch('claudewatch.focus.subprocess')
    def test_applescript_contains_tty_session_matching(self, mock_subprocess):
        fm = FocusManager()
        fm._focus_iterm('/dev/ttys099')
        script = mock_subprocess.run.call_args[0][0][2]
        assert 'tty of s is "/dev/ttys099"' in script
        # iTerm script iterates sessions within tabs within windows
        assert 'repeat with s in sessions of t' in script


# ---------------------------------------------------------------------------
# _focus_app
# ---------------------------------------------------------------------------

class TestFocusApp:

    @patch('claudewatch.focus.subprocess')
    def test_calls_osascript_to_activate_app(self, mock_subprocess):
        fm = FocusManager()
        fm._focus_app('Visual Studio Code')
        mock_subprocess.run.assert_called_once_with(
            ['osascript', '-e', 'tell application "Visual Studio Code" to activate'],
            timeout=3,
        )

    @patch('claudewatch.focus.subprocess')
    def test_different_app_name(self, mock_subprocess):
        fm = FocusManager()
        fm._focus_app('iTerm2')
        mock_subprocess.run.assert_called_once_with(
            ['osascript', '-e', 'tell application "iTerm2" to activate'],
            timeout=3,
        )

    @patch('claudewatch.focus.subprocess')
    def test_swallows_exceptions(self, mock_subprocess):
        mock_subprocess.run.side_effect = subprocess.TimeoutExpired(cmd='osascript', timeout=3)
        fm = FocusManager()
        # Should not raise
        fm._focus_app('Terminal')


# ---------------------------------------------------------------------------
# is_session_focused
# ---------------------------------------------------------------------------

class TestIsSessionFocused:

    @patch('claudewatch.focus.NSWorkspace')
    def test_returns_true_when_frontmost_matches_bundle_id(self, mock_workspace):
        mock_app = MagicMock()
        mock_app.bundleIdentifier.return_value = 'com.microsoft.VSCode'
        mock_workspace.sharedWorkspace.return_value.frontmostApplication.return_value = mock_app

        fm = FocusManager()
        result = fm.is_session_focused(_session(ide='VS Code'))
        assert result is True

    @patch('claudewatch.focus.NSWorkspace')
    def test_returns_false_when_different_app_is_frontmost(self, mock_workspace):
        mock_app = MagicMock()
        mock_app.bundleIdentifier.return_value = 'com.apple.Safari'
        mock_workspace.sharedWorkspace.return_value.frontmostApplication.return_value = mock_app

        fm = FocusManager()
        result = fm.is_session_focused(_session(ide='VS Code'))
        assert result is False

    @patch('claudewatch.focus.NSWorkspace')
    def test_returns_false_when_no_frontmost_app(self, mock_workspace):
        mock_workspace.sharedWorkspace.return_value.frontmostApplication.return_value = None

        fm = FocusManager()
        result = fm.is_session_focused(_session(ide='VS Code'))
        assert result is False

    @patch('claudewatch.focus.NSWorkspace')
    def test_returns_false_on_exception(self, mock_workspace):
        mock_workspace.sharedWorkspace.side_effect = RuntimeError('NSWorkspace broken')

        fm = FocusManager()
        result = fm.is_session_focused(_session(ide='VS Code'))
        assert result is False

    @patch('claudewatch.focus.NSWorkspace')
    def test_falls_back_to_localized_name_for_unknown_ide(self, mock_workspace):
        """For IDEs not in BUNDLE_ID_MAP, comparison uses localizedName."""
        mock_app = MagicMock()
        mock_app.localizedName.return_value = 'Sublime Text'
        mock_workspace.sharedWorkspace.return_value.frontmostApplication.return_value = mock_app

        fm = FocusManager()
        # 'Sublime Text' is not in BUNDLE_ID_MAP, so falls back to name comparison
        result = fm.is_session_focused(_session(ide='Sublime Text'))
        assert result is True
        mock_app.localizedName.assert_called()

    @patch('claudewatch.focus.NSWorkspace')
    def test_localized_name_fallback_returns_false_on_mismatch(self, mock_workspace):
        mock_app = MagicMock()
        mock_app.localizedName.return_value = 'Atom'
        mock_workspace.sharedWorkspace.return_value.frontmostApplication.return_value = mock_app

        fm = FocusManager()
        result = fm.is_session_focused(_session(ide='Sublime Text'))
        assert result is False

    @patch('claudewatch.focus.NSWorkspace')
    def test_cursor_bundle_id_match(self, mock_workspace):
        """Cursor has a non-obvious bundle ID; verify it works."""
        mock_app = MagicMock()
        mock_app.bundleIdentifier.return_value = 'com.todesktop.230313mzl4w4u92'
        mock_workspace.sharedWorkspace.return_value.frontmostApplication.return_value = mock_app

        fm = FocusManager()
        assert fm.is_session_focused(_session(ide='Cursor')) is True

    @patch('claudewatch.focus.NSWorkspace')
    def test_iterm_bundle_id_match(self, mock_workspace):
        mock_app = MagicMock()
        mock_app.bundleIdentifier.return_value = 'com.googlecode.iterm2'
        mock_workspace.sharedWorkspace.return_value.frontmostApplication.return_value = mock_app

        fm = FocusManager()
        assert fm.is_session_focused(_session(ide='iTerm')) is True

    @patch('claudewatch.focus.NSWorkspace')
    def test_empty_ide_with_matching_localized_name(self, mock_workspace):
        """Empty ide string leads to falsy app_name, returns falsy."""
        mock_app = MagicMock()
        mock_app.localizedName.return_value = ''
        mock_workspace.sharedWorkspace.return_value.frontmostApplication.return_value = mock_app

        fm = FocusManager()
        result = fm.is_session_focused(_session(ide=''))
        assert not result

    @patch('claudewatch.focus.NSWorkspace')
    def test_known_ide_uses_bundle_id_not_localized_name(self, mock_workspace):
        """When an IDE is in BUNDLE_ID_MAP, bundleIdentifier is used,
        not localizedName."""
        mock_app = MagicMock()
        mock_app.bundleIdentifier.return_value = 'com.apple.Terminal'
        mock_workspace.sharedWorkspace.return_value.frontmostApplication.return_value = mock_app

        fm = FocusManager()
        result = fm.is_session_focused(_session(ide='Terminal'))
        assert result is True
        mock_app.bundleIdentifier.assert_called()
        mock_app.localizedName.assert_not_called()


# ---------------------------------------------------------------------------
# get_app_icon
# ---------------------------------------------------------------------------

class TestGetAppIcon:

    def setup_method(self):
        """Clear the class-level icon cache before each test."""
        FocusManager._icon_cache.clear()

    @patch('claudewatch.focus.os.path.exists')
    @patch('builtins.open', create=True)
    @patch('claudewatch.focus.plistlib.load')
    @patch('claudewatch.focus.NSWorkspace')
    def test_returns_icon_path_when_found(self, mock_workspace, mock_plist_load,
                                          mock_open, mock_exists):
        mock_workspace.sharedWorkspace.return_value.fullPathForApplication_.return_value = (
            '/Applications/Visual Studio Code.app'
        )
        mock_exists.return_value = True
        mock_plist_load.return_value = {'CFBundleIconFile': 'Code.icns'}

        fm = FocusManager()
        result = fm.get_app_icon('VS Code')
        expected = '/Applications/Visual Studio Code.app/Contents/Resources/Code.icns'
        assert result == expected

    @patch('claudewatch.focus.os.path.exists')
    @patch('builtins.open', create=True)
    @patch('claudewatch.focus.plistlib.load')
    @patch('claudewatch.focus.NSWorkspace')
    def test_appends_icns_extension_when_missing(self, mock_workspace, mock_plist_load,
                                                  mock_open, mock_exists):
        mock_workspace.sharedWorkspace.return_value.fullPathForApplication_.return_value = (
            '/Applications/Terminal.app'
        )
        mock_exists.return_value = True
        mock_plist_load.return_value = {'CFBundleIconFile': 'Terminal'}

        fm = FocusManager()
        result = fm.get_app_icon('Terminal')
        assert result.endswith('.icns')
        assert 'Terminal.icns' in result

    @patch('claudewatch.focus.NSWorkspace')
    def test_returns_none_when_app_not_found(self, mock_workspace):
        mock_workspace.sharedWorkspace.return_value.fullPathForApplication_.return_value = None

        fm = FocusManager()
        result = fm.get_app_icon('NonexistentEditor')
        assert result is None

    @patch('claudewatch.focus.NSWorkspace')
    def test_caches_results(self, mock_workspace):
        mock_workspace.sharedWorkspace.return_value.fullPathForApplication_.return_value = None

        fm = FocusManager()
        result1 = fm.get_app_icon('CachedEditor')
        result2 = fm.get_app_icon('CachedEditor')

        assert result1 is None
        assert result2 is None
        # fullPathForApplication_ should only be called once due to caching
        assert mock_workspace.sharedWorkspace.return_value.fullPathForApplication_.call_count == 1

    @patch('claudewatch.focus.NSWorkspace')
    def test_caches_none_result(self, mock_workspace):
        """Even None results should be cached to avoid repeated lookups."""
        mock_workspace.sharedWorkspace.return_value.fullPathForApplication_.return_value = None

        fm = FocusManager()
        fm.get_app_icon('MissingApp')
        assert 'MissingApp' in FocusManager._icon_cache
        assert FocusManager._icon_cache['MissingApp'] is None

    @patch('claudewatch.focus.os.path.exists')
    @patch('builtins.open', create=True)
    @patch('claudewatch.focus.plistlib.load')
    @patch('claudewatch.focus.NSWorkspace')
    def test_caches_successful_result(self, mock_workspace, mock_plist_load,
                                       mock_open, mock_exists):
        mock_workspace.sharedWorkspace.return_value.fullPathForApplication_.return_value = (
            '/Applications/Cursor.app'
        )
        mock_exists.return_value = True
        mock_plist_load.return_value = {'CFBundleIconFile': 'cursor.icns'}

        fm = FocusManager()
        result = fm.get_app_icon('Cursor')
        assert 'Cursor' in FocusManager._icon_cache
        assert FocusManager._icon_cache['Cursor'] == result

    @patch('claudewatch.focus.NSWorkspace')
    def test_handles_exception_gracefully(self, mock_workspace):
        mock_workspace.sharedWorkspace.side_effect = RuntimeError('NSWorkspace error')

        fm = FocusManager()
        result = fm.get_app_icon('BrokenApp')
        assert result is None

    @patch('claudewatch.focus.os.path.exists')
    @patch('builtins.open', create=True)
    @patch('claudewatch.focus.plistlib.load')
    @patch('claudewatch.focus.NSWorkspace')
    def test_returns_none_when_plist_has_no_icon_file(self, mock_workspace, mock_plist_load,
                                                       mock_open, mock_exists):
        mock_workspace.sharedWorkspace.return_value.fullPathForApplication_.return_value = (
            '/Applications/SomeApp.app'
        )
        mock_exists.return_value = True
        mock_plist_load.return_value = {}  # No CFBundleIconFile

        fm = FocusManager()
        result = fm.get_app_icon('SomeApp')
        assert result is None

    @patch('claudewatch.focus.os.path.exists')
    @patch('builtins.open', create=True)
    @patch('claudewatch.focus.plistlib.load')
    @patch('claudewatch.focus.NSWorkspace')
    def test_returns_none_when_icon_file_does_not_exist(self, mock_workspace, mock_plist_load,
                                                         mock_open, mock_exists):
        mock_workspace.sharedWorkspace.return_value.fullPathForApplication_.return_value = (
            '/Applications/SomeApp.app'
        )
        # First call: plist_path exists. Second call: icon file does not exist.
        mock_exists.side_effect = [True, False]
        mock_plist_load.return_value = {'CFBundleIconFile': 'icon.icns'}

        fm = FocusManager()
        result = fm.get_app_icon('SomeApp')
        assert result is None

    @patch('claudewatch.focus.NSWorkspace')
    def test_uses_app_name_map_for_lookup(self, mock_workspace):
        """get_app_icon should translate ide_label via APP_NAME_MAP."""
        mock_ws = mock_workspace.sharedWorkspace.return_value
        mock_ws.fullPathForApplication_.return_value = None

        fm = FocusManager()
        fm.get_app_icon('VS Code')
        mock_ws.fullPathForApplication_.assert_called_once_with('Visual Studio Code')

    @patch('claudewatch.focus.NSWorkspace')
    def test_unknown_label_uses_label_as_app_name(self, mock_workspace):
        """If ide_label is not in APP_NAME_MAP, use the label directly."""
        mock_ws = mock_workspace.sharedWorkspace.return_value
        mock_ws.fullPathForApplication_.return_value = None

        fm = FocusManager()
        fm.get_app_icon('UnknownEditor')
        mock_ws.fullPathForApplication_.assert_called_once_with('UnknownEditor')


# ---------------------------------------------------------------------------
# APP_NAME_MAP and BUNDLE_ID_MAP consistency
# ---------------------------------------------------------------------------

class TestMappingConsistency:
    """Verify that the two maps cover the same set of IDE labels."""

    def test_bundle_id_map_keys_match_app_name_map_keys(self):
        fm = FocusManager()
        assert set(fm.BUNDLE_ID_MAP.keys()) == set(fm.APP_NAME_MAP.keys())

    def test_ide_uri_schemes_are_subset_of_app_name_map(self):
        fm = FocusManager()
        assert set(fm._IDE_URI_SCHEMES.keys()).issubset(set(fm.APP_NAME_MAP.keys()))
