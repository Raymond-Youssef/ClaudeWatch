"""FocusManager — AppleScript IDE/terminal focusing."""

import os
import plistlib
import re
import subprocess

from AppKit import NSWorkspace

_SAFE_TTY_RE = re.compile(r'[^a-zA-Z0-9/]')


class FocusManager:
    _icon_cache = {}  # class-level cache: ide_label -> icns_path or None
    APP_NAME_MAP = {
        'VS Code': 'Visual Studio Code',
        'RubyMine': 'RubyMine',
        'PyCharm': 'PyCharm',
        'IntelliJ': 'IntelliJ IDEA',
        'WebStorm': 'WebStorm',
        'GoLand': 'GoLand',
        'Cursor': 'Cursor',
        'Claude': 'Claude',
        'iTerm': 'iTerm2',
        'Terminal': 'Terminal',
        'Warp': 'Warp',
        'Alacritty': 'Alacritty',
        'Kitty': 'kitty',
    }

    # Bundle IDs for focus detection (localizedName can differ from app name)
    BUNDLE_ID_MAP = {
        'VS Code': 'com.microsoft.VSCode',
        'RubyMine': 'com.jetbrains.rubymine',
        'PyCharm': 'com.jetbrains.pycharm',
        'IntelliJ': 'com.jetbrains.intellij',
        'WebStorm': 'com.jetbrains.WebStorm',
        'GoLand': 'com.jetbrains.goland',
        'Cursor': 'com.todesktop.230313mzl4w4u92',
        'Claude': 'com.anthropic.claudefordesktop',
        'iTerm': 'com.googlecode.iterm2',
        'Terminal': 'com.apple.Terminal',
        'Warp': 'dev.warp.Warp-Stable',
        'Alacritty': 'org.alacritty',
        'Kitty': 'net.kovidgoyal.kitty',
    }

    def is_session_focused(self, session):
        """Check if the session's IDE/terminal is the frontmost app."""
        ide = session.get('ide', '')
        bundle_id = self.BUNDLE_ID_MAP.get(ide)
        try:
            front = NSWorkspace.sharedWorkspace().frontmostApplication()
            if not front:
                return False
            if bundle_id:
                return front.bundleIdentifier() == bundle_id
            # Fallback to name comparison for unknown IDEs
            app_name = self.APP_NAME_MAP.get(ide, ide)
            return app_name and front.localizedName() == app_name
        except Exception:
            return False

    def get_app_icon(self, ide_label):
        """Return the path to the .icns icon for an IDE/terminal, or None."""
        if ide_label in self._icon_cache:
            return self._icon_cache[ide_label]

        app_name = self.APP_NAME_MAP.get(ide_label, ide_label)
        icon_path = None
        try:
            ws = NSWorkspace.sharedWorkspace()
            app_path = ws.fullPathForApplication_(app_name)
            if app_path:
                plist_path = os.path.join(app_path, 'Contents', 'Info.plist')
                if os.path.exists(plist_path):
                    with open(plist_path, 'rb') as f:
                        plist = plistlib.load(f)
                    icon_file = plist.get('CFBundleIconFile', '')
                    if icon_file:
                        if not icon_file.endswith('.icns'):
                            icon_file += '.icns'
                        candidate = os.path.join(app_path, 'Contents', 'Resources', icon_file)
                        if os.path.exists(candidate):
                            icon_path = candidate
        except Exception:
            pass

        self._icon_cache[ide_label] = icon_path
        return icon_path

    def focus_session(self, session):
        """Bring the IDE/terminal window for a session to the foreground."""
        ide = session.get('ide', '')
        tty = _SAFE_TTY_RE.sub('', session.get('tty') or '')

        if ide == 'Terminal' and tty:
            if self._focus_terminal(tty):
                return

        if ide == 'iTerm' and tty:
            if self._focus_iterm(tty):
                return

        app_name = self.APP_NAME_MAP.get(ide, ide)
        if app_name:
            self._focus_app(app_name)

    def _focus_terminal(self, tty):
        """Focus exact Terminal.app tab by TTY."""
        try:
            subprocess.run(['osascript', '-e', f'''
                tell application "Terminal"
                    activate
                    repeat with w in windows
                        repeat with t in tabs of w
                            if tty of t is "{tty}" then
                                set selected of t to true
                                set index of w to 1
                                return
                            end if
                        end repeat
                    end repeat
                end tell
            '''], timeout=3)
            return True
        except Exception:
            return False

    def _focus_iterm(self, tty):
        """Focus exact iTerm2 session by TTY."""
        try:
            subprocess.run(['osascript', '-e', f'''
                tell application "iTerm2"
                    activate
                    repeat with w in windows
                        repeat with t in tabs of w
                            repeat with s in sessions of t
                                if tty of s is "{tty}" then
                                    select t
                                    select s
                                    set index of w to 1
                                    return
                                end if
                            end repeat
                        end repeat
                    end repeat
                end tell
            '''], timeout=3)
            return True
        except Exception:
            return False

    def _focus_app(self, app_name):
        """Activate an application by name."""
        try:
            subprocess.run([
                'osascript', '-e',
                f'tell application "{app_name}" to activate'
            ], timeout=3)
        except Exception:
            pass
