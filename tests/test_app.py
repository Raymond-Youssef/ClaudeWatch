"""Tests for claudewatch.app module (thin rumps shell).

The app is a thin shell; most logic lives in controller.py.
We test format_duration here as an integration check since app.py
re-exports it from controller.
"""

from claudewatch.controller import format_duration


class TestFormatDuration:
    def test_seconds(self):
        assert format_duration(45) == "45s"

    def test_minutes(self):
        assert format_duration(150) == "2m"

    def test_hours(self):
        assert format_duration(3700) == "1h 1m"

    def test_zero(self):
        assert format_duration(0) == "0s"

    def test_boundary_60(self):
        assert format_duration(60) == "1m"

    def test_boundary_3600(self):
        assert format_duration(3600) == "1h 0m"
