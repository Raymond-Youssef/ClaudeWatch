"""Notifier — sending + handling macOS notifications via UNUserNotificationCenter."""

import time
import uuid

import objc

APP_NAME = 'ClaudeWatch'


def _load_un_framework():
    """Load UserNotifications framework and register required block signatures."""
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


_load_un_framework()

UNUserNotificationCenter = objc.lookUpClass('UNUserNotificationCenter')
UNMutableNotificationContent = objc.lookUpClass('UNMutableNotificationContent')
UNNotificationRequest = objc.lookUpClass('UNNotificationRequest')


class _DelegateBase:
    """Protocol methods for UNUserNotificationCenterDelegate."""
    pass


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


class Notifier:
    def __init__(self):
        self._center = UNUserNotificationCenter.currentNotificationCenter()
        self._delegate = NotificationDelegate.alloc().init()
        self._center.setDelegate_(self._delegate)
        self._history: dict[str, float] = {}
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

    def notify(self, title, message, pid=None):
        """Send a notification via UNUserNotificationCenter.

        Duplicate notifications (same title + message) are suppressed
        for COOLDOWN_SECONDS to avoid spamming the user.
        """
        dedup_key = f"{title}:{message}"
        now = time.monotonic()
        last_sent = self._history.get(dedup_key)
        if last_sent is not None and (now - last_sent) < COOLDOWN_SECONDS:
            return
        self._history[dedup_key] = now

        content = UNMutableNotificationContent.alloc().init()
        content.setTitle_(APP_NAME)
        content.setSubtitle_(title)
        content.setBody_(message or '')
        if pid is not None:
            content.setUserInfo_({'pid': pid})

        request = UNNotificationRequest.requestWithIdentifier_content_trigger_(
            str(uuid.uuid4()), content, None
        )
        self._center.addNotificationRequest_withCompletionHandler_(
            request, lambda error: None
        )

    def register_handler(self, callback):
        """Register a callback for notification clicks."""
        self._delegate.setClickCallback_(callback)
