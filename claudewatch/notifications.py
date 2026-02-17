"""Notifier — sending + handling macOS notifications."""

import rumps

APP_NAME = 'ClaudeWatch'


class Notifier:
    def __init__(self):
        self._click_callback = None

    def notify(self, title, message, pid=None):
        """Send macOS notification with optional session PID as data."""
        rumps.notification(APP_NAME, title, message, data={'pid': pid} if pid else None)

    def register_handler(self, callback):
        """Store the callback for notification clicks.

        The actual @rumps.notifications decorator must be set up in the App
        class (rumps requires it at module level or in __init__). This just
        stores the callback so the app can delegate to it.
        """
        self._click_callback = callback

    def handle_click(self, info):
        """Called by the app's @rumps.notifications handler."""
        if self._click_callback and info:
            self._click_callback(info)
