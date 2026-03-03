"""Notifier — sending + handling macOS notifications via UNUserNotificationCenter."""

import time
import uuid

import objc

APP_NAME = 'ClaudeWatch'

_framework_loaded = False


def _load_un_framework():
    """Load UserNotifications framework and register required block signatures."""
    global _framework_loaded
    if _framework_loaded:
        return
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
    objc.registerMetaDataForSelector(
        b'UNUserNotificationCenter',
        b'addNotificationRequest:withCompletionHandler:',
        {
            'arguments': {
                3: {
                    'callable': {
                        'retval': {'type': b'v'},
                        'arguments': {
                            0: {'type': b'^v'},
                            1: {'type': b'@'},
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
    _framework_loaded = True


NSObject = objc.lookUpClass('NSObject')

# Register the delegate protocol methods so PyObjC knows about the signatures
objc.registerMetaDataForSelector(
    b'NSObject',
    b'userNotificationCenter:didReceiveNotificationResponse:withCompletionHandler:',
    {
        'arguments': {
            4: {
                'callable': {
                    'retval': {'type': b'v'},
                    'arguments': {
                        0: {'type': b'^v'},
                    },
                },
            },
        },
    },
)


class NotificationDelegate(NSObject):
    """Handles notification interactions (clicks)."""

    def init(self):
        self = objc.super(NotificationDelegate, self).init()
        if self is None:
            return None
        self._click_callback = None
        return self

    def setClickCallback_(self, callback):
        self._click_callback = callback

    def userNotificationCenter_didReceiveNotificationResponse_withCompletionHandler_(
        self, center, response, completion_handler
    ):
        user_info = response.notification().request().content().userInfo()
        if self._click_callback and user_info:
            pid = user_info.get('pid')
            if pid:
                self._click_callback({'pid': pid})
        completion_handler()


COOLDOWN_SECONDS = 30


class NotificationThrottle:
    """Pure dedup/cooldown logic for notification rate-limiting."""

    def __init__(self, cooldown_seconds=COOLDOWN_SECONDS):
        self._cooldown = cooldown_seconds
        self._history: dict[str, float] = {}

    def should_send(self, dedup_key):
        """Return True if this key hasn't been sent within the cooldown period."""
        now = time.monotonic()
        last_sent = self._history.get(dedup_key)
        if last_sent is not None and (now - last_sent) < self._cooldown:
            return False
        return True

    def record_sent(self, dedup_key):
        """Record that a notification was sent for this key."""
        self._history[dedup_key] = time.monotonic()
        self.prune()

    def prune(self):
        """Remove expired entries to prevent unbounded growth."""
        now = time.monotonic()
        expired = [k for k, v in self._history.items() if (now - v) >= self._cooldown]
        for k in expired:
            del self._history[k]


class Notifier:
    def __init__(self):
        _load_un_framework()
        UNUserNotificationCenter = objc.lookUpClass('UNUserNotificationCenter')
        self._UNMutableNotificationContent = objc.lookUpClass('UNMutableNotificationContent')
        self._UNNotificationRequest = objc.lookUpClass('UNNotificationRequest')
        self._center = UNUserNotificationCenter.currentNotificationCenter()
        self._delegate = NotificationDelegate.alloc().init()
        self._center.setDelegate_(self._delegate)
        self._throttle = NotificationThrottle()
        self._request_authorization()

    def _request_authorization(self):
        """Request macOS notification permission (alert + sound)."""
        try:
            self._center.requestAuthorizationWithOptions_completionHandler_(
                (1 << 2) | (1 << 1),
                lambda granted, error: None,
            )
        except Exception:
            pass

    def notify(self, title, message, pid=None, body=None):
        """Send a notification via UNUserNotificationCenter.

        Duplicate notifications (same title + message) are suppressed
        for COOLDOWN_SECONDS to avoid spamming the user.
        """
        dedup_key = f"{title}:{message}"
        if not self._throttle.should_send(dedup_key):
            return
        self._throttle.record_sent(dedup_key)

        content = self._UNMutableNotificationContent.alloc().init()
        content.setTitle_(APP_NAME)
        content.setSubtitle_(title)
        content.setBody_(body or message or '')
        if pid is not None:
            content.setUserInfo_({'pid': pid})

        request = self._UNNotificationRequest.requestWithIdentifier_content_trigger_(
            str(uuid.uuid4()), content, None
        )
        self._center.addNotificationRequest_withCompletionHandler_(
            request, lambda error: None
        )

    def register_handler(self, callback):
        """Register a callback for notification clicks."""
        self._delegate.setClickCallback_(callback)
