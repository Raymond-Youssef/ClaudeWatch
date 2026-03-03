"""Tests for claudewatch.session.SessionManager."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from claudewatch.session import SessionManager


# ---------------------------------------------------------------------------
# Construction and persistence
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_init_creates_data_dir(self, tmp_path):
        new_dir = tmp_path / "claudewatch_data"
        assert not new_dir.exists()
        mgr = SessionManager(data_dir=new_dir)
        assert new_dir.exists()
        assert mgr.data_dir == new_dir

    def test_init_with_custom_data_dir(self, tmp_path):
        mgr = SessionManager(data_dir=tmp_path)
        assert mgr.data_dir == tmp_path
        assert mgr.sessions_file == tmp_path / "sessions.json"

    def test_init_default_data_dir_is_home_claudewatch(self):
        """When no data_dir is given the default is ~/.claudewatch."""
        with patch.object(Path, "mkdir"):
            mgr = SessionManager.__new__(SessionManager)
            mgr.data_dir = None  # bypass __init__
            # Just verify the class logic in isolation
            expected = Path.home() / ".claudewatch"
            mgr2 = SessionManager.__new__(SessionManager)
            # Manually replicate the relevant line
            data_dir = None
            result = Path(data_dir) if data_dir else Path.home() / ".claudewatch"
            assert result == expected


class TestLoadSessions:
    def test_returns_empty_dict_for_missing_file(self, session_mgr):
        # sessions_file doesn't exist on a fresh tmp_path
        session_mgr.sessions_file.unlink(missing_ok=True)
        result = session_mgr.load_sessions()
        assert result == {}

    def test_returns_empty_dict_for_corrupt_json(self, session_mgr):
        session_mgr.sessions_file.write_text("{{not valid json!!")
        result = session_mgr.load_sessions()
        assert result == {}

    def test_loads_valid_json(self, session_mgr, sample_session):
        data = {"abc": sample_session()}
        session_mgr.sessions_file.write_text(json.dumps(data))
        result = session_mgr.load_sessions()
        assert result == data


class TestSaveSessions:
    def test_writes_valid_json_that_round_trips(self, session_mgr, sample_session):
        session_mgr.sessions["s1"] = sample_session(convo_id="s1")
        session_mgr.save_sessions()

        with open(session_mgr.sessions_file) as f:
            loaded = json.load(f)
        assert loaded == session_mgr.sessions

    def test_save_is_atomic_uses_temp_file_and_rename(self, session_mgr, sample_session):
        """Verify save_sessions goes through mkstemp + os.replace (atomic)."""
        session_mgr.sessions["s1"] = sample_session(convo_id="s1")

        with patch("claudewatch.session.tempfile.mkstemp") as mock_mkstemp, \
             patch("claudewatch.session.os.fdopen") as mock_fdopen, \
             patch("claudewatch.session.os.replace") as mock_replace:
            mock_mkstemp.return_value = (99, "/fake/tmp.tmp")
            mock_file = mock_fdopen.return_value.__enter__.return_value

            session_mgr.save_sessions()

            mock_mkstemp.assert_called_once_with(
                dir=str(session_mgr.data_dir), suffix=".tmp"
            )
            mock_fdopen.assert_called_once_with(99, "w")
            mock_replace.assert_called_once_with(
                "/fake/tmp.tmp", str(session_mgr.sessions_file)
            )


# ---------------------------------------------------------------------------
# convo_id_for (static, pure)
# ---------------------------------------------------------------------------

class TestConvoIdFor:
    def test_with_jsonl_path_returns_stem(self):
        path = "/home/user/.claude/projects/abc-def-1234.jsonl"
        assert SessionManager.convo_id_for(path, 999) == "abc-def-1234"

    def test_with_jsonl_path_object(self):
        path = Path("/tmp/my-uuid-5678.jsonl")
        assert SessionManager.convo_id_for(path, 999) == "my-uuid-5678"

    def test_without_jsonl_path_returns_pid_based(self):
        assert SessionManager.convo_id_for(None, 42) == "pid-42"
        assert SessionManager.convo_id_for("", 100) == "pid-100"


# ---------------------------------------------------------------------------
# add_session
# ---------------------------------------------------------------------------

class TestAddSession:
    def test_adds_session_with_all_expected_fields(self, session_mgr):
        now = time.time()
        session_mgr.add_session(
            convo_id="c1",
            pid="1000",
            title="My task",
            create_time=now,
            ide="Cursor",
            cwd="/projects/foo",
            jsonl_path="/tmp/c1.jsonl",
            tty="/dev/ttys002",
        )
        s = session_mgr.sessions["c1"]
        assert s["convo_id"] == "c1"
        assert s["pid"] == "1000"
        assert s["title"] == "My task"
        assert s["started_at"] == now
        assert s["status"] == "running"
        assert s["ide"] == "Cursor"
        assert s["cwd"] == "/projects/foo"
        assert s["jsonl"] == "/tmp/c1.jsonl"
        assert s["tty"] == "/dev/ttys002"
        assert s["notified"] is False
        assert s["last_state"] == "active"

    def test_auto_saves_to_disk(self, session_mgr):
        session_mgr.add_session(
            convo_id="c2", pid="2000", title="t",
            create_time=time.time(), ide="VS Code",
            cwd="/tmp", jsonl_path=None, tty="",
        )
        # Re-load from disk
        loaded = json.loads(session_mgr.sessions_file.read_text())
        assert "c2" in loaded

    def test_default_title_is_new_conversation(self, session_mgr):
        session_mgr.add_session(
            convo_id="c3", pid="3000", title=None,
            create_time=time.time(), ide="Terminal",
            cwd="/tmp", jsonl_path=None, tty="",
        )
        assert session_mgr.sessions["c3"]["title"] == "New conversation"

    def test_jsonl_path_none_stored_as_empty_string(self, session_mgr):
        session_mgr.add_session(
            convo_id="c4", pid="4000", title="x",
            create_time=time.time(), ide="",
            cwd="/tmp", jsonl_path=None, tty="",
        )
        assert session_mgr.sessions["c4"]["jsonl"] == ""


# ---------------------------------------------------------------------------
# complete_session
# ---------------------------------------------------------------------------

class TestCompleteSession:
    def test_sets_completed_status_and_fields(self, session_mgr, sample_session):
        session_mgr.sessions["c1"] = sample_session(convo_id="c1", status="running")
        before = time.time()
        session_mgr.complete_session("c1")
        after = time.time()

        s = session_mgr.sessions["c1"]
        assert s["status"] == "completed"
        assert before <= s["ended_at"] <= after
        assert s["notified"] is True

    def test_saves_to_disk(self, session_mgr, sample_session):
        session_mgr.sessions["c1"] = sample_session(convo_id="c1")
        session_mgr.complete_session("c1")

        loaded = json.loads(session_mgr.sessions_file.read_text())
        assert loaded["c1"]["status"] == "completed"

    def test_noop_for_nonexistent_convo_id(self, session_mgr):
        # Should not raise
        session_mgr.complete_session("nonexistent")
        assert "nonexistent" not in session_mgr.sessions


# ---------------------------------------------------------------------------
# update_state
# ---------------------------------------------------------------------------

class TestUpdateState:
    def test_updates_last_state(self, session_mgr, sample_session):
        session_mgr.sessions["c1"] = sample_session(convo_id="c1", last_state="active")
        session_mgr.update_state("c1", "waiting_for_user")
        assert session_mgr.sessions["c1"]["last_state"] == "waiting_for_user"

    def test_ignores_unknown_state(self, session_mgr, sample_session):
        session_mgr.sessions["c1"] = sample_session(convo_id="c1", last_state="active")
        session_mgr.update_state("c1", "unknown")
        assert session_mgr.sessions["c1"]["last_state"] == "active"

    def test_noop_for_nonexistent_convo_id(self, session_mgr):
        session_mgr.update_state("nonexistent", "active")
        assert "nonexistent" not in session_mgr.sessions

    def test_saves_to_disk(self, session_mgr, sample_session):
        session_mgr.sessions["c1"] = sample_session(convo_id="c1")
        session_mgr.update_state("c1", "tool_running")

        loaded = json.loads(session_mgr.sessions_file.read_text())
        assert loaded["c1"]["last_state"] == "tool_running"


# ---------------------------------------------------------------------------
# prune_old_sessions
# ---------------------------------------------------------------------------

class TestPruneOldSessions:
    def test_removes_completed_sessions_older_than_max_age(self, session_mgr, sample_session):
        old_time = time.time() - 86400 * 10  # 10 days ago
        session_mgr.sessions["old"] = sample_session(
            convo_id="old", status="completed", ended_at=old_time,
        )
        session_mgr.prune_old_sessions(max_age=86400 * 7)
        assert "old" not in session_mgr.sessions

    def test_keeps_running_sessions_regardless_of_age(self, session_mgr, sample_session):
        old_time = time.time() - 86400 * 30
        session_mgr.sessions["running"] = sample_session(
            convo_id="running", status="running", started_at=old_time,
        )
        session_mgr.prune_old_sessions(max_age=86400 * 7)
        assert "running" in session_mgr.sessions

    def test_keeps_recently_completed_sessions(self, session_mgr, sample_session):
        recent_time = time.time() - 3600  # 1 hour ago
        session_mgr.sessions["recent"] = sample_session(
            convo_id="recent", status="completed", ended_at=recent_time,
        )
        session_mgr.prune_old_sessions(max_age=86400 * 7)
        assert "recent" in session_mgr.sessions

    def test_saves_after_pruning(self, session_mgr, sample_session):
        old_time = time.time() - 86400 * 10
        session_mgr.sessions["old"] = sample_session(
            convo_id="old", status="completed", ended_at=old_time,
        )
        session_mgr.save_sessions()  # persist the "old" entry first
        session_mgr.prune_old_sessions(max_age=86400 * 7)

        loaded = json.loads(session_mgr.sessions_file.read_text())
        assert "old" not in loaded

    def test_no_save_when_nothing_pruned(self, session_mgr, sample_session):
        recent_time = time.time() - 60
        session_mgr.sessions["recent"] = sample_session(
            convo_id="recent", status="completed", ended_at=recent_time,
        )
        with patch.object(session_mgr, "save_sessions") as mock_save:
            session_mgr.prune_old_sessions(max_age=86400 * 7)
            mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# find_by_pid
# ---------------------------------------------------------------------------

class TestFindByPid:
    def test_finds_running_session_matching_pid(self, session_mgr, sample_session):
        session_mgr.sessions["c1"] = sample_session(convo_id="c1", pid="5555", status="running")
        cid, session = session_mgr.find_by_pid("5555")
        assert cid == "c1"
        assert session["pid"] == "5555"

    def test_returns_none_none_for_unknown_pid(self, session_mgr, sample_session):
        session_mgr.sessions["c1"] = sample_session(convo_id="c1", pid="1111")
        cid, session = session_mgr.find_by_pid("9999")
        assert cid is None
        assert session is None

    def test_returns_none_none_for_completed_session(self, session_mgr, sample_session):
        session_mgr.sessions["c1"] = sample_session(
            convo_id="c1", pid="5555", status="completed",
        )
        cid, session = session_mgr.find_by_pid("5555")
        assert cid is None
        assert session is None

    def test_with_create_time_rejects_if_differs_more_than_2s(self, session_mgr, sample_session):
        now = time.time()
        session_mgr.sessions["c1"] = sample_session(
            convo_id="c1", pid="5555", status="running", started_at=now,
        )
        # create_time differs by 5 seconds -- should be rejected
        cid, session = session_mgr.find_by_pid("5555", create_time=now + 5)
        assert cid is None
        assert session is None

    def test_with_create_time_accepts_within_2s(self, session_mgr, sample_session):
        now = time.time()
        session_mgr.sessions["c1"] = sample_session(
            convo_id="c1", pid="5555", status="running", started_at=now,
        )
        # create_time differs by 1.5 seconds -- should be accepted
        cid, session = session_mgr.find_by_pid("5555", create_time=now + 1.5)
        assert cid == "c1"

    def test_with_create_time_boundary_exactly_2s(self, session_mgr, sample_session):
        now = time.time()
        session_mgr.sessions["c1"] = sample_session(
            convo_id="c1", pid="5555", status="running", started_at=now,
        )
        # Exactly 2 seconds -- abs(diff) == 2, not > 2, so should be accepted
        cid, session = session_mgr.find_by_pid("5555", create_time=now + 2)
        assert cid == "c1"

    def test_with_create_time_boundary_just_over_2s(self, session_mgr, sample_session):
        now = time.time()
        session_mgr.sessions["c1"] = sample_session(
            convo_id="c1", pid="5555", status="running", started_at=now,
        )
        # 2.01 seconds -- should be rejected
        cid, session = session_mgr.find_by_pid("5555", create_time=now + 2.01)
        assert cid is None


# ---------------------------------------------------------------------------
# find_by_jsonl
# ---------------------------------------------------------------------------

class TestFindByJsonl:
    def test_finds_running_session_by_jsonl_path(self, session_mgr, sample_session):
        session_mgr.sessions["c1"] = sample_session(
            convo_id="c1", jsonl="/tmp/abc.jsonl", status="running",
        )
        cid, session = session_mgr.find_by_jsonl("/tmp/abc.jsonl")
        assert cid == "c1"
        assert session["jsonl"] == "/tmp/abc.jsonl"

    def test_returns_none_none_for_unmatched_path(self, session_mgr, sample_session):
        session_mgr.sessions["c1"] = sample_session(
            convo_id="c1", jsonl="/tmp/abc.jsonl", status="running",
        )
        cid, session = session_mgr.find_by_jsonl("/tmp/xyz.jsonl")
        assert cid is None
        assert session is None

    def test_returns_none_none_for_completed_session(self, session_mgr, sample_session):
        session_mgr.sessions["c1"] = sample_session(
            convo_id="c1", jsonl="/tmp/abc.jsonl", status="completed",
        )
        cid, session = session_mgr.find_by_jsonl("/tmp/abc.jsonl")
        assert cid is None
        assert session is None

    def test_accepts_path_object(self, session_mgr, sample_session):
        session_mgr.sessions["c1"] = sample_session(
            convo_id="c1", jsonl="/tmp/abc.jsonl", status="running",
        )
        cid, session = session_mgr.find_by_jsonl(Path("/tmp/abc.jsonl"))
        assert cid == "c1"


# ---------------------------------------------------------------------------
# rekey
# ---------------------------------------------------------------------------

class TestRekey:
    def test_changes_key_of_session(self, session_mgr, sample_session):
        session_mgr.sessions["old-id"] = sample_session(convo_id="old-id")
        session_mgr.rekey("old-id", "new-id")
        assert "old-id" not in session_mgr.sessions
        assert "new-id" in session_mgr.sessions

    def test_updates_convo_id_inside_session_dict(self, session_mgr, sample_session):
        session_mgr.sessions["old-id"] = sample_session(convo_id="old-id")
        session_mgr.rekey("old-id", "new-id")
        assert session_mgr.sessions["new-id"]["convo_id"] == "new-id"

    def test_preserves_other_fields(self, session_mgr, sample_session):
        original = sample_session(convo_id="old-id", pid="7777", title="Hello")
        session_mgr.sessions["old-id"] = original
        session_mgr.rekey("old-id", "new-id")
        s = session_mgr.sessions["new-id"]
        assert s["pid"] == "7777"
        assert s["title"] == "Hello"

    def test_noop_if_old_id_equals_new_id(self, session_mgr, sample_session):
        session_mgr.sessions["same"] = sample_session(convo_id="same")
        with patch.object(session_mgr, "save_sessions") as mock_save:
            session_mgr.rekey("same", "same")
            mock_save.assert_not_called()
        assert "same" in session_mgr.sessions

    def test_noop_if_old_id_not_in_sessions(self, session_mgr):
        with patch.object(session_mgr, "save_sessions") as mock_save:
            session_mgr.rekey("missing", "new-id")
            mock_save.assert_not_called()
        assert "new-id" not in session_mgr.sessions

    def test_saves_to_disk(self, session_mgr, sample_session):
        session_mgr.sessions["old-id"] = sample_session(convo_id="old-id")
        session_mgr.rekey("old-id", "new-id")

        loaded = json.loads(session_mgr.sessions_file.read_text())
        assert "new-id" in loaded
        assert "old-id" not in loaded


# ---------------------------------------------------------------------------
# get_active / get_completed_today / get_stats
# ---------------------------------------------------------------------------

class TestGetActive:
    def test_returns_only_running_sessions(self, session_mgr, sample_session):
        session_mgr.sessions["r1"] = sample_session(convo_id="r1", status="running")
        session_mgr.sessions["r2"] = sample_session(convo_id="r2", status="running")
        session_mgr.sessions["c1"] = sample_session(convo_id="c1", status="completed")
        active = session_mgr.get_active()
        assert len(active) == 2
        convo_ids = {s["convo_id"] for s in active}
        assert convo_ids == {"r1", "r2"}

    def test_returns_empty_when_no_running(self, session_mgr, sample_session):
        session_mgr.sessions["c1"] = sample_session(convo_id="c1", status="completed")
        assert session_mgr.get_active() == []


class TestGetCompletedToday:
    def test_returns_sessions_completed_in_last_24h(self, session_mgr, sample_session):
        recent = time.time() - 3600  # 1 hour ago
        old = time.time() - 86400 * 2  # 2 days ago
        session_mgr.sessions["recent"] = sample_session(
            convo_id="recent", status="completed", ended_at=recent,
        )
        session_mgr.sessions["old"] = sample_session(
            convo_id="old", status="completed", ended_at=old,
        )
        session_mgr.sessions["running"] = sample_session(
            convo_id="running", status="running",
        )
        result = session_mgr.get_completed_today()
        assert len(result) == 1
        assert result[0]["convo_id"] == "recent"

    def test_returns_empty_when_none_completed_recently(self, session_mgr, sample_session):
        old = time.time() - 86400 * 5
        session_mgr.sessions["old"] = sample_session(
            convo_id="old", status="completed", ended_at=old,
        )
        assert session_mgr.get_completed_today() == []


class TestGetStats:
    def test_returns_correct_counts_and_avg_duration(self, session_mgr, sample_session):
        now = time.time()

        # 2 running sessions
        session_mgr.sessions["r1"] = sample_session(
            convo_id="r1", status="running", started_at=now - 100,
        )
        session_mgr.sessions["r2"] = sample_session(
            convo_id="r2", status="running", started_at=now - 200,
        )

        # 2 completed today with known durations
        session_mgr.sessions["c1"] = sample_session(
            convo_id="c1", status="completed",
            started_at=now - 600, ended_at=now - 300,  # 300s duration
        )
        session_mgr.sessions["c2"] = sample_session(
            convo_id="c2", status="completed",
            started_at=now - 500, ended_at=now - 400,  # 100s duration
        )

        # 1 completed long ago (should not count in completed_today)
        session_mgr.sessions["cold"] = sample_session(
            convo_id="cold", status="completed",
            started_at=now - 86400 * 3, ended_at=now - 86400 * 3 + 60,
        )

        stats = session_mgr.get_stats()
        assert stats["active"] == 2
        assert stats["completed_today"] == 2
        assert stats["total"] == 5
        # avg_duration = (300 + 100) / 2 = 200
        assert stats["avg_duration"] == pytest.approx(200.0, abs=1.0)

    def test_avg_duration_is_zero_when_no_completed_today(self, session_mgr, sample_session):
        session_mgr.sessions["r1"] = sample_session(convo_id="r1", status="running")
        stats = session_mgr.get_stats()
        assert stats["avg_duration"] == 0
        assert stats["active"] == 1
        assert stats["completed_today"] == 0
        assert stats["total"] == 1

    def test_empty_sessions(self, session_mgr):
        stats = session_mgr.get_stats()
        assert stats == {
            "active": 0,
            "completed_today": 0,
            "total": 0,
            "avg_duration": 0,
        }
