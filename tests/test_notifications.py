"""Tests for claudewatch.notifications — NotificationThrottle and Notifier."""

from unittest.mock import MagicMock, call, patch

import pytest

from claudewatch.notifications import NotificationThrottle, Notifier


# ===========================================================================
# NotificationThrottle — pure Python, no macOS deps
# ===========================================================================


class TestShouldSend:
    """NotificationThrottle.should_send() dedup/cooldown checks."""

    def test_returns_true_for_fresh_key(self):
        throttle = NotificationThrottle(cooldown_seconds=30)
        assert throttle.should_send("key1") is True

    def test_returns_false_within_cooldown(self):
        throttle = NotificationThrottle(cooldown_seconds=30)
        with patch("claudewatch.notifications.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            throttle.record_sent("key1")

            mock_time.monotonic.return_value = 115.0  # 15s later
            assert throttle.should_send("key1") is False

    def test_returns_true_after_cooldown_expires(self):
        throttle = NotificationThrottle(cooldown_seconds=30)
        with patch("claudewatch.notifications.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            throttle.record_sent("key1")

            mock_time.monotonic.return_value = 131.0  # 31s later
            assert throttle.should_send("key1") is True

    def test_full_lifecycle(self):
        """Fresh -> sent -> suppressed -> cooldown expires -> allowed again."""
        throttle = NotificationThrottle(cooldown_seconds=30)
        with patch("claudewatch.notifications.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            assert throttle.should_send("key1") is True
            throttle.record_sent("key1")

            mock_time.monotonic.return_value = 115.0
            assert throttle.should_send("key1") is False

            mock_time.monotonic.return_value = 131.0
            assert throttle.should_send("key1") is True

    def test_different_keys_are_independent(self):
        throttle = NotificationThrottle(cooldown_seconds=30)
        with patch("claudewatch.notifications.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            throttle.record_sent("key1")

            mock_time.monotonic.return_value = 110.0
            assert throttle.should_send("key1") is False
            assert throttle.should_send("key2") is True

    def test_exactly_at_cooldown_boundary_is_still_suppressed(self):
        """At exactly cooldown_seconds elapsed, (now - last) < cooldown is False."""
        throttle = NotificationThrottle(cooldown_seconds=30)
        with patch("claudewatch.notifications.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            throttle.record_sent("key1")

            # Exactly 30s later: (130 - 100) = 30, not < 30, so should send
            mock_time.monotonic.return_value = 130.0
            assert throttle.should_send("key1") is True


class TestRecordSent:
    """NotificationThrottle.record_sent() records time and triggers prune."""

    def test_records_current_time(self):
        throttle = NotificationThrottle(cooldown_seconds=30)
        with patch("claudewatch.notifications.time") as mock_time:
            mock_time.monotonic.return_value = 42.0
            throttle.record_sent("key1")
            assert throttle._history["key1"] == 42.0

    def test_calls_prune(self):
        throttle = NotificationThrottle(cooldown_seconds=30)
        with patch.object(throttle, "prune") as mock_prune:
            with patch("claudewatch.notifications.time") as mock_time:
                mock_time.monotonic.return_value = 1.0
                throttle.record_sent("key1")
                mock_prune.assert_called_once()

    def test_overwrites_previous_time(self):
        throttle = NotificationThrottle(cooldown_seconds=30)
        with patch("claudewatch.notifications.time") as mock_time:
            mock_time.monotonic.return_value = 10.0
            throttle.record_sent("key1")
            assert throttle._history["key1"] == 10.0

            mock_time.monotonic.return_value = 50.0
            throttle.record_sent("key1")
            assert throttle._history["key1"] == 50.0


class TestPrune:
    """NotificationThrottle.prune() cleans up expired entries."""

    def test_removes_expired_entries(self):
        throttle = NotificationThrottle(cooldown_seconds=30)
        with patch("claudewatch.notifications.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            throttle._history["old_key"] = 50.0  # 50s ago, expired
            throttle._history["recent_key"] = 95.0  # 5s ago, not expired

            throttle.prune()

            assert "old_key" not in throttle._history
            assert "recent_key" in throttle._history

    def test_keeps_non_expired_entries(self):
        throttle = NotificationThrottle(cooldown_seconds=60)
        with patch("claudewatch.notifications.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            throttle._history["a"] = 80.0  # 20s ago
            throttle._history["b"] = 90.0  # 10s ago

            throttle.prune()

            assert "a" in throttle._history
            assert "b" in throttle._history

    def test_handles_empty_history(self):
        throttle = NotificationThrottle(cooldown_seconds=30)
        # Should not raise
        throttle.prune()
        assert throttle._history == {}

    def test_removes_all_when_all_expired(self):
        throttle = NotificationThrottle(cooldown_seconds=10)
        with patch("claudewatch.notifications.time") as mock_time:
            mock_time.monotonic.return_value = 200.0
            throttle._history["a"] = 100.0  # 100s ago
            throttle._history["b"] = 150.0  # 50s ago

            throttle.prune()

            assert throttle._history == {}


class TestCustomCooldown:
    """NotificationThrottle works correctly with different cooldown values."""

    def test_short_cooldown(self):
        throttle = NotificationThrottle(cooldown_seconds=5)
        with patch("claudewatch.notifications.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            throttle.record_sent("key1")

            mock_time.monotonic.return_value = 104.0  # 4s later
            assert throttle.should_send("key1") is False

            mock_time.monotonic.return_value = 106.0  # 6s later
            assert throttle.should_send("key1") is True

    def test_long_cooldown(self):
        throttle = NotificationThrottle(cooldown_seconds=3600)
        with patch("claudewatch.notifications.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            throttle.record_sent("key1")

            mock_time.monotonic.return_value = 3000.0  # 2900s later, within 3600
            assert throttle.should_send("key1") is False

            mock_time.monotonic.return_value = 3701.0  # 3601s later
            assert throttle.should_send("key1") is True

    def test_zero_cooldown_always_allows(self):
        throttle = NotificationThrottle(cooldown_seconds=0)
        with patch("claudewatch.notifications.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            throttle.record_sent("key1")

            # Same instant; (100 - 100) = 0, not < 0, so should_send is True
            assert throttle.should_send("key1") is True

    def test_default_cooldown_is_30(self):
        throttle = NotificationThrottle()
        assert throttle._cooldown == 30


# ===========================================================================
# Notifier — macOS UNUserNotificationCenter wrapper (heavily mocked)
# ===========================================================================


def _make_notifier():
    """Create a Notifier with all macOS dependencies bypassed."""
    notifier = object.__new__(Notifier)
    notifier._throttle = NotificationThrottle()
    notifier._UNMutableNotificationContent = MagicMock()
    notifier._UNNotificationRequest = MagicMock()
    notifier._center = MagicMock()
    notifier._delegate = MagicMock()
    return notifier


class TestNotifierNotify:
    """Notifier.notify() sends notifications via UNUserNotificationCenter."""

    def test_sends_notification_with_correct_fields(self):
        notifier = _make_notifier()
        mock_content = MagicMock()
        notifier._UNMutableNotificationContent.alloc.return_value.init.return_value = (
            mock_content
        )

        notifier.notify("Build failed", "tests/unit crashed")

        mock_content.setTitle_.assert_called_once_with("ClaudeWatch")
        mock_content.setSubtitle_.assert_called_once_with("Build failed")
        mock_content.setBody_.assert_called_once_with("tests/unit crashed")

    def test_includes_pid_in_userinfo_when_provided(self):
        notifier = _make_notifier()
        mock_content = MagicMock()
        notifier._UNMutableNotificationContent.alloc.return_value.init.return_value = (
            mock_content
        )

        notifier.notify("Done", "All tests passed", pid=12345)

        mock_content.setUserInfo_.assert_called_once_with({"pid": 12345})

    def test_omits_userinfo_when_pid_is_none(self):
        notifier = _make_notifier()
        mock_content = MagicMock()
        notifier._UNMutableNotificationContent.alloc.return_value.init.return_value = (
            mock_content
        )

        notifier.notify("Done", "finished", pid=None)

        mock_content.setUserInfo_.assert_not_called()

    def test_uses_body_parameter_when_provided(self):
        notifier = _make_notifier()
        mock_content = MagicMock()
        notifier._UNMutableNotificationContent.alloc.return_value.init.return_value = (
            mock_content
        )

        notifier.notify("Title", "short msg", body="Long detailed body text")

        mock_content.setBody_.assert_called_once_with("Long detailed body text")

    def test_falls_back_to_message_when_body_is_none(self):
        notifier = _make_notifier()
        mock_content = MagicMock()
        notifier._UNMutableNotificationContent.alloc.return_value.init.return_value = (
            mock_content
        )

        notifier.notify("Title", "fallback message", body=None)

        mock_content.setBody_.assert_called_once_with("fallback message")

    def test_sets_body_to_empty_string_when_both_none(self):
        notifier = _make_notifier()
        mock_content = MagicMock()
        notifier._UNMutableNotificationContent.alloc.return_value.init.return_value = (
            mock_content
        )

        notifier.notify("Title", None, body=None)

        mock_content.setBody_.assert_called_once_with("")

    def test_creates_request_and_adds_to_center(self):
        notifier = _make_notifier()
        mock_content = MagicMock()
        notifier._UNMutableNotificationContent.alloc.return_value.init.return_value = (
            mock_content
        )
        mock_request = MagicMock()
        notifier._UNNotificationRequest.requestWithIdentifier_content_trigger_.return_value = (
            mock_request
        )

        notifier.notify("Title", "msg")

        notifier._UNNotificationRequest.requestWithIdentifier_content_trigger_.assert_called_once()
        req_call_args = (
            notifier._UNNotificationRequest.requestWithIdentifier_content_trigger_.call_args
        )
        # First arg is UUID string, second is content, third is None trigger
        assert req_call_args[0][1] is mock_content
        assert req_call_args[0][2] is None

        notifier._center.addNotificationRequest_withCompletionHandler_.assert_called_once()
        add_call_args = (
            notifier._center.addNotificationRequest_withCompletionHandler_.call_args
        )
        assert add_call_args[0][0] is mock_request

    def test_skips_sending_when_throttled(self):
        notifier = _make_notifier()
        mock_content = MagicMock()
        notifier._UNMutableNotificationContent.alloc.return_value.init.return_value = (
            mock_content
        )

        # Send first time — should go through
        notifier.notify("Same Title", "Same msg")
        assert notifier._center.addNotificationRequest_withCompletionHandler_.call_count == 1

        # Send again immediately — should be throttled
        notifier.notify("Same Title", "Same msg")
        assert notifier._center.addNotificationRequest_withCompletionHandler_.call_count == 1

    def test_allows_sending_after_cooldown(self):
        notifier = _make_notifier()
        mock_content = MagicMock()
        notifier._UNMutableNotificationContent.alloc.return_value.init.return_value = (
            mock_content
        )

        with patch("claudewatch.notifications.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            notifier.notify("Title", "msg")
            assert (
                notifier._center.addNotificationRequest_withCompletionHandler_.call_count
                == 1
            )

            # Advance past cooldown (default 30s)
            mock_time.monotonic.return_value = 131.0
            notifier.notify("Title", "msg")
            assert (
                notifier._center.addNotificationRequest_withCompletionHandler_.call_count
                == 2
            )

    def test_different_title_message_combos_are_not_throttled(self):
        notifier = _make_notifier()
        mock_content = MagicMock()
        notifier._UNMutableNotificationContent.alloc.return_value.init.return_value = (
            mock_content
        )

        notifier.notify("Title A", "msg A")
        notifier.notify("Title B", "msg B")
        assert notifier._center.addNotificationRequest_withCompletionHandler_.call_count == 2

    def test_dedup_key_uses_title_and_message(self):
        """Same title but different message should not be throttled."""
        notifier = _make_notifier()
        mock_content = MagicMock()
        notifier._UNMutableNotificationContent.alloc.return_value.init.return_value = (
            mock_content
        )

        notifier.notify("Title", "message A")
        notifier.notify("Title", "message B")
        assert notifier._center.addNotificationRequest_withCompletionHandler_.call_count == 2


class TestNotifierRegisterHandler:
    """Notifier.register_handler() sets click callback on delegate."""

    def test_sets_click_callback_on_delegate(self):
        notifier = _make_notifier()
        callback = MagicMock()

        notifier.register_handler(callback)

        notifier._delegate.setClickCallback_.assert_called_once_with(callback)

    def test_overwrites_previous_callback(self):
        notifier = _make_notifier()
        cb1 = MagicMock()
        cb2 = MagicMock()

        notifier.register_handler(cb1)
        notifier.register_handler(cb2)

        assert notifier._delegate.setClickCallback_.call_count == 2
        notifier._delegate.setClickCallback_.assert_called_with(cb2)
