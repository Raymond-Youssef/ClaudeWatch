"""FocusManager — AppleScript IDE/terminal focusing."""

import subprocess


class FocusManager:
    APP_NAME_MAP = {
        'VS Code': 'Visual Studio Code',
        'RubyMine': 'RubyMine',
        'PyCharm': 'PyCharm',
        'IntelliJ': 'IntelliJ IDEA',
        'WebStorm': 'WebStorm',
        'GoLand': 'GoLand',
        'Cursor': 'Cursor',
        'iTerm': 'iTerm2',
        'Terminal': 'Terminal',
        'Warp': 'Warp',
        'Alacritty': 'Alacritty',
        'Kitty': 'kitty',
    }

    def focus_session(self, session):
        """Bring the IDE/terminal window for a session to the foreground."""
        ide = session.get('ide', '')
        tty = session.get('tty', '')

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
