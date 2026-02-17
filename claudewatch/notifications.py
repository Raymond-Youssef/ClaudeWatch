"""Notifier — sending + handling macOS notifications."""

import objc
import rumps

APP_NAME = 'ClaudeWatch'


class Notifier:
    def __init__(self):
        self._click_callback = None
        self._request_authorization()

    @staticmethod
    def _request_authorization():
        """Request macOS notification permission (triggers the system prompt)."""
        try:
            # Register block signature metadata before loading the framework
            objc.registerMetaDataForSelector(
                b'UNUserNotificationCenter',
                b'requestAuthorizationWithOptions:completionHandler:',
                {
                    'arguments': {
                        3: {
                            'callable': {
                                'retval': {'type': b'v'},
                                'arguments': {
                                    0: {'type': b'^v'},
                                    1: {'type': b'B'},
                                    2: {'type': b'@'},
                                },
                            },
                        },
                    },
                },
            )
            objc.loadBundle(
                'UserNotifications',
                bundle_path='/System/Library/Frameworks/UserNotifications.framework',
                module_globals=globals(),
            )
            UNUserNotificationCenter = objc.lookUpClass('UNUserNotificationCenter')
            center = UNUserNotificationCenter.currentNotificationCenter()
            # UNAuthorizationOptionAlert (1 << 2) | UNAuthorizationOptionSound (1 << 1)
            center.requestAuthorizationWithOptions_completionHandler_(
                (1 << 2) | (1 << 1),
                lambda granted, error: None,
            )
        except Exception:
            pass

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
