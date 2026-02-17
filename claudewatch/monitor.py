"""ProcessMonitor — background process scanning for Claude Code sessions."""

import os
import threading
import time

import psutil


class ProcessMonitor:
    IDE_PATTERNS = {
        'rubymine': 'RubyMine',
        'code helper': 'VS Code',
        'vscode': 'VS Code',
        'electron': 'VS Code',
        'pycharm': 'PyCharm',
        'intellij': 'IntelliJ',
        'webstorm': 'WebStorm',
        'goland': 'GoLand',
        'cursor': 'Cursor',
        'iterm': 'iTerm',
        'terminal': 'Terminal',
        'warp': 'Warp',
        'alacritty': 'Alacritty',
        'kitty': 'Kitty',
    }

    def __init__(self, on_scan):
        self._on_scan = on_scan
        self._running = False
        self._thread = None

    def start(self):
        """Start the background monitoring thread."""
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Signal the monitoring thread to stop."""
        self._running = False

    def _loop(self):
        while self._running:
            self._on_scan()
            time.sleep(2)

    def scan_processes(self):
        """Scan for running claude-code processes.

        Returns a dict of {pid_str: metadata} for each active Claude Code process.
        """
        results = {}
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
            try:
                cmdline = proc.info['cmdline']
                if cmdline and self.is_claude_code_process(proc.info):
                    pid = str(proc.info['pid'])
                    tty = None
                    try:
                        tty = psutil.Process(int(pid)).terminal()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                    results[pid] = {
                        'cmdline': cmdline,
                        'create_time': proc.info['create_time'],
                        'cwd': self.get_session_cwd(pid),
                        'ide': self.detect_parent_ide(proc),
                        'tty': tty,
                    }
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return results

    @staticmethod
    def is_claude_code_process(proc_info):
        """Check if a process is a Claude Code CLI session."""
        cmdline = proc_info['cmdline'] or []
        cmdline_str = ' '.join(cmdline)

        if '/Applications/Claude.app' in cmdline_str or 'chrome-native-host' in cmdline_str:
            return False

        for arg in cmdline:
            basename = os.path.basename(arg)
            if basename in ('claude', 'claude-code'):
                return True

        return False

    def detect_parent_ide(self, proc):
        """Walk the ancestor process chain to detect the IDE/terminal."""
        try:
            ancestor = proc.parent()
            while ancestor and ancestor.pid > 1:
                name = ancestor.name().lower()
                for pattern, label in self.IDE_PATTERNS.items():
                    if pattern in name:
                        return label
                ancestor = ancestor.parent()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return 'Terminal'

    @staticmethod
    def get_session_cwd(pid):
        """Get the working directory of a process."""
        try:
            return psutil.Process(int(pid)).cwd()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None
