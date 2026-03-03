"""Tests for claudewatch.jsonl — JSONL parsing and session state logic."""

import json
from pathlib import Path

import pytest

from claudewatch.jsonl import _strip_system_tags, _strip_xml_tags, JsonlParser
from tests.conftest import (
    make_assistant_entry,
    make_text_block,
    make_thinking_block,
    make_tool_use_block,
    make_user_entry,
)


# ---------------------------------------------------------------------------
# _strip_system_tags
# ---------------------------------------------------------------------------
class TestStripSystemTags:
    def test_plain_text_unchanged(self):
        assert _strip_system_tags("hello world") == "hello world"

    def test_empty_string(self):
        assert _strip_system_tags("") == ""

    def test_removes_system_reminder_block(self):
        text = "before <system-reminder>secret stuff</system-reminder> after"
        assert _strip_system_tags(text) == "before  after"

    def test_removes_local_command_caveat_block(self):
        text = "<local-command-caveat>caveat content</local-command-caveat>keep"
        assert _strip_system_tags(text) == "keep"

    def test_removes_command_name_block(self):
        text = "start <command-name>ls</command-name> end"
        assert _strip_system_tags(text) == "start  end"

    def test_removes_command_message_block(self):
        text = "<command-message>msg</command-message>ok"
        assert _strip_system_tags(text) == "ok"

    def test_removes_command_args_block(self):
        text = "x<command-args>--flag</command-args>y"
        assert _strip_system_tags(text) == "xy"

    def test_removes_local_command_stdout_block(self):
        text = "before<local-command-stdout>output\nlines</local-command-stdout>after"
        assert _strip_system_tags(text) == "beforeafter"

    def test_removes_multiline_system_tag(self):
        text = (
            "preamble\n"
            "<system-reminder>\n"
            "line1\n"
            "line2\n"
            "</system-reminder>\n"
            "postamble"
        )
        result = _strip_system_tags(text)
        assert "line1" not in result
        assert "line2" not in result
        assert "preamble" in result
        assert "postamble" in result

    def test_removes_multiple_system_tags(self):
        text = (
            "<system-reminder>a</system-reminder>"
            "middle"
            "<command-name>b</command-name>"
        )
        assert _strip_system_tags(text) == "middle"

    def test_preserves_regular_xml_tags(self):
        text = "<bold>hello</bold>"
        assert _strip_system_tags(text) == "<bold>hello</bold>"

    def test_only_whitespace_after_strip(self):
        text = "  <system-reminder>all</system-reminder>  "
        assert _strip_system_tags(text) == ""


# ---------------------------------------------------------------------------
# _strip_xml_tags
# ---------------------------------------------------------------------------
class TestStripXmlTags:
    def test_plain_text_unchanged(self):
        assert _strip_xml_tags("hello world") == "hello world"

    def test_empty_string(self):
        assert _strip_xml_tags("") == ""

    def test_strips_regular_xml_tags_preserves_text(self):
        assert _strip_xml_tags("<b>bold</b> text") == "bold text"

    def test_removes_system_tags_completely(self):
        text = "<system-reminder>secret</system-reminder>visible"
        assert _strip_xml_tags(text) == "visible"
        assert "secret" not in _strip_xml_tags(text)

    def test_mixed_system_and_regular_tags(self):
        text = (
            "<system-reminder>hidden</system-reminder>"
            "<p>Hello <b>world</b></p>"
        )
        result = _strip_xml_tags(text)
        assert result == "Hello world"
        assert "hidden" not in result

    def test_collapses_whitespace(self):
        text = "  foo   <tag>bar</tag>   baz  "
        assert _strip_xml_tags(text) == "foo bar baz"

    def test_collapses_whitespace_after_system_tag_removal(self):
        text = "before  <system-reminder>x</system-reminder>  after"
        result = _strip_xml_tags(text)
        assert result == "before after"

    def test_nested_tags(self):
        text = "<div><span>inner text</span></div>"
        assert _strip_xml_tags(text) == "inner text"

    def test_self_closing_tags(self):
        text = "before <br/> after"
        assert _strip_xml_tags(text) == "before after"

    def test_newlines_collapsed_to_spaces(self):
        text = "line1\n\nline2\n\nline3"
        assert _strip_xml_tags(text) == "line1 line2 line3"


# ---------------------------------------------------------------------------
# JsonlParser.get_project_dir
# ---------------------------------------------------------------------------
class TestGetProjectDir:
    def test_standard_path(self):
        result = JsonlParser.get_project_dir("/Users/foo/my-project")
        expected = Path.home() / ".claude" / "projects" / "-Users-foo-my-project"
        assert result == expected

    def test_special_chars_replaced_by_hyphens(self):
        result = JsonlParser.get_project_dir("/tmp/my project (v2)")
        dir_name = result.name
        # All non-alphanumeric chars should be hyphens
        assert " " not in dir_name
        assert "(" not in dir_name
        assert ")" not in dir_name
        assert dir_name == "-tmp-my-project--v2-"

    def test_root_path(self):
        result = JsonlParser.get_project_dir("/")
        expected = Path.home() / ".claude" / "projects" / "-"
        assert result == expected

    def test_returns_path_object(self):
        result = JsonlParser.get_project_dir("/some/path")
        assert isinstance(result, Path)

    def test_path_with_dots(self):
        result = JsonlParser.get_project_dir("/home/user/.config/app")
        dir_name = result.name
        assert "." not in dir_name
        assert dir_name == "-home-user--config-app"


# ---------------------------------------------------------------------------
# JsonlParser._has_conversation
# ---------------------------------------------------------------------------
class TestHasConversation:
    def test_file_with_user_message(self, write_jsonl):
        path = write_jsonl([make_user_entry("hello")])
        assert JsonlParser._has_conversation(path) is True

    def test_file_with_assistant_message(self, write_jsonl):
        path = write_jsonl([
            make_assistant_entry([make_text_block("response")])
        ])
        assert JsonlParser._has_conversation(path) is True

    def test_file_with_only_system_entries(self, write_jsonl):
        entries = [
            {"type": "system", "message": {"role": "system", "content": "init"}},
            {"type": "progress", "data": {"percent": 50}},
        ]
        path = write_jsonl(entries)
        assert JsonlParser._has_conversation(path) is False

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        assert JsonlParser._has_conversation(path) is False

    def test_nonexistent_file(self, tmp_path):
        path = tmp_path / "does_not_exist.jsonl"
        assert JsonlParser._has_conversation(path) is False

    def test_mixed_entries_returns_true(self, write_jsonl):
        entries = [
            {"type": "system", "message": {"role": "system", "content": "init"}},
            make_user_entry("hi"),
        ]
        path = write_jsonl(entries)
        assert JsonlParser._has_conversation(path) is True

    def test_blank_lines_ignored(self, tmp_path):
        path = tmp_path / "blanks.jsonl"
        content = (
            "\n"
            + json.dumps(make_user_entry("hello"))
            + "\n\n"
        )
        path.write_text(content)
        assert JsonlParser._has_conversation(path) is True


# ---------------------------------------------------------------------------
# JsonlParser.get_conversation_title
# ---------------------------------------------------------------------------
class TestGetConversationTitle:
    def test_simple_text_content_string(self, write_jsonl):
        entry = {
            "type": "user",
            "message": {
                "role": "user",
                "content": "What is Python?",
            },
        }
        path = write_jsonl([entry])
        assert JsonlParser.get_conversation_title(path) == "What is Python?"

    def test_content_as_list_of_text_blocks(self, write_jsonl):
        path = write_jsonl([make_user_entry("Fix the bug")])
        assert JsonlParser.get_conversation_title(path) == "Fix the bug"

    def test_content_with_system_tags_stripped(self, write_jsonl):
        entry = {
            "type": "user",
            "message": {
                "role": "user",
                "content": "<system-reminder>ignore</system-reminder>Real question here",
            },
        }
        path = write_jsonl([entry])
        assert JsonlParser.get_conversation_title(path) == "Real question here"

    def test_content_with_xml_tags_stripped(self, write_jsonl):
        entry = {
            "type": "user",
            "message": {
                "role": "user",
                "content": "<b>Bold title</b> text",
            },
        }
        path = write_jsonl([entry])
        assert JsonlParser.get_conversation_title(path) == "Bold title text"

    def test_no_user_messages_returns_none(self, write_jsonl):
        path = write_jsonl([
            make_assistant_entry([make_text_block("response")])
        ])
        assert JsonlParser.get_conversation_title(path) is None

    def test_none_path_returns_none(self):
        assert JsonlParser.get_conversation_title(None) is None

    def test_empty_path_string_returns_none(self):
        assert JsonlParser.get_conversation_title("") is None

    def test_skips_system_entries_finds_first_user(self, write_jsonl):
        entries = [
            {"type": "system", "message": {"role": "system", "content": "init"}},
            make_user_entry("first question"),
            make_user_entry("second question"),
        ]
        path = write_jsonl(entries)
        assert JsonlParser.get_conversation_title(path) == "first question"

    def test_user_message_with_empty_content(self, write_jsonl):
        entries = [
            {
                "type": "user",
                "message": {"role": "user", "content": ""},
            },
            make_user_entry("fallback title"),
        ]
        path = write_jsonl(entries)
        assert JsonlParser.get_conversation_title(path) == "fallback title"

    def test_content_list_with_multiple_blocks(self, write_jsonl):
        entry = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "image", "data": "..."},
                    {"type": "text", "text": "Describe this image"},
                ],
            },
        }
        path = write_jsonl([entry])
        assert JsonlParser.get_conversation_title(path) == "Describe this image"

    def test_content_list_with_only_non_text_blocks(self, write_jsonl):
        entry = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "image", "data": "..."},
                ],
            },
        }
        path = write_jsonl([entry])
        assert JsonlParser.get_conversation_title(path) is None

    def test_system_tags_in_list_block_stripped(self, write_jsonl):
        entry = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "<system-reminder>ctx</system-reminder>Actual prompt",
                    }
                ],
            },
        }
        path = write_jsonl([entry])
        assert JsonlParser.get_conversation_title(path) == "Actual prompt"


# ---------------------------------------------------------------------------
# JsonlParser.get_latest_response
# ---------------------------------------------------------------------------
class TestGetLatestResponse:
    def test_single_assistant_message(self, write_jsonl):
        path = write_jsonl([
            make_user_entry("hi"),
            make_assistant_entry([make_text_block("Hello there!")]),
        ])
        assert JsonlParser.get_latest_response(path) == "Hello there!"

    def test_multiple_assistant_messages_returns_last(self, write_jsonl):
        path = write_jsonl([
            make_user_entry("hi"),
            make_assistant_entry([make_text_block("first response")]),
            make_user_entry("more"),
            make_assistant_entry([make_text_block("second response")]),
        ])
        assert JsonlParser.get_latest_response(path) == "second response"

    def test_no_assistant_messages_returns_none(self, write_jsonl):
        path = write_jsonl([make_user_entry("hi")])
        assert JsonlParser.get_latest_response(path) is None

    def test_none_path_returns_none(self):
        assert JsonlParser.get_latest_response(None) is None

    def test_empty_path_returns_none(self):
        assert JsonlParser.get_latest_response("") is None

    def test_assistant_with_multiple_text_blocks_returns_last(self, write_jsonl):
        path = write_jsonl([
            make_assistant_entry([
                make_text_block("first block"),
                make_text_block("second block"),
            ]),
        ])
        assert JsonlParser.get_latest_response(path) == "second block"

    def test_assistant_with_only_tool_use_returns_none(self, write_jsonl):
        path = write_jsonl([
            make_assistant_entry([make_tool_use_block()]),
        ])
        assert JsonlParser.get_latest_response(path) is None

    def test_strips_xml_tags_from_response(self, write_jsonl):
        path = write_jsonl([
            make_assistant_entry([make_text_block("<b>formatted</b> text")]),
        ])
        assert JsonlParser.get_latest_response(path) == "formatted text"

    def test_skips_non_message_entries(self, write_jsonl):
        entries = [
            make_assistant_entry([make_text_block("real response")]),
            {"type": "progress", "data": {"percent": 100}},
        ]
        path = write_jsonl(entries)
        assert JsonlParser.get_latest_response(path) == "real response"

    def test_assistant_with_thinking_and_text(self, write_jsonl):
        path = write_jsonl([
            make_assistant_entry([
                make_thinking_block("let me think..."),
                make_text_block("Here is my answer"),
            ]),
        ])
        assert JsonlParser.get_latest_response(path) == "Here is my answer"

    def test_whitespace_only_text_block_skipped(self, write_jsonl):
        """Text blocks with only whitespace are ignored."""
        path = write_jsonl([
            make_assistant_entry([
                make_text_block("good answer"),
                make_text_block("   "),
            ]),
        ])
        # The last non-whitespace text block is "good answer"
        assert JsonlParser.get_latest_response(path) == "good answer"


# ---------------------------------------------------------------------------
# JsonlParser.get_session_state
# ---------------------------------------------------------------------------
class TestGetSessionState:
    def test_last_entry_tool_use_returns_waiting_tool(self, write_jsonl):
        path = write_jsonl([
            make_user_entry("read file"),
            make_assistant_entry([
                make_text_block("I'll read it"),
                make_tool_use_block("Read"),
            ]),
        ])
        assert JsonlParser.get_session_state(str(path)) == "waiting_tool"

    def test_last_entry_text_returns_waiting_input(self, write_jsonl):
        path = write_jsonl([
            make_user_entry("hello"),
            make_assistant_entry([make_text_block("How can I help?")]),
        ])
        assert JsonlParser.get_session_state(str(path)) == "waiting_input"

    def test_last_entry_thinking_returns_active(self, write_jsonl):
        path = write_jsonl([
            make_user_entry("hello"),
            make_assistant_entry([make_thinking_block("pondering...")]),
        ])
        assert JsonlParser.get_session_state(str(path)) == "active"

    def test_last_entry_user_message_returns_active(self, write_jsonl):
        path = write_jsonl([
            make_user_entry("new prompt"),
        ])
        assert JsonlParser.get_session_state(str(path)) == "active"

    def test_empty_file_returns_unknown(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        assert JsonlParser.get_session_state(str(path)) == "unknown"

    def test_nonexistent_file_returns_unknown(self, tmp_path):
        path = tmp_path / "nope.jsonl"
        assert JsonlParser.get_session_state(str(path)) == "unknown"

    def test_none_path_returns_unknown(self):
        assert JsonlParser.get_session_state(None) == "unknown"

    def test_empty_string_returns_unknown(self):
        assert JsonlParser.get_session_state("") == "unknown"

    def test_skips_progress_entries(self, write_jsonl):
        entries = [
            make_assistant_entry([make_text_block("done")]),
            {"type": "progress", "data": {"percent": 100}},
        ]
        path = write_jsonl(entries)
        assert JsonlParser.get_session_state(str(path)) == "waiting_input"

    def test_skips_system_entries(self, write_jsonl):
        entries = [
            make_user_entry("go"),
            {"type": "system", "message": {"role": "system", "content": "ctx"}},
        ]
        path = write_jsonl(entries)
        assert JsonlParser.get_session_state(str(path)) == "active"

    def test_skips_file_history_snapshot(self, write_jsonl):
        entries = [
            make_assistant_entry([make_tool_use_block("Bash")]),
            {"type": "file-history-snapshot", "files": []},
        ]
        path = write_jsonl(entries)
        assert JsonlParser.get_session_state(str(path)) == "waiting_tool"

    def test_assistant_empty_content_returns_unknown(self, write_jsonl):
        entry = {
            "type": "assistant",
            "message": {"role": "assistant", "content": []},
        }
        path = write_jsonl([entry])
        assert JsonlParser.get_session_state(str(path)) == "unknown"

    def test_complex_conversation_returns_correct_state(self, write_jsonl):
        """Full conversation flow: the last relevant entry determines state."""
        entries = [
            make_user_entry("Fix the bug"),
            make_assistant_entry([make_thinking_block("analyzing...")]),
            make_assistant_entry([
                make_text_block("I found the issue"),
                make_tool_use_block("Edit"),
            ]),
            make_user_entry("yes, apply it"),
            make_assistant_entry([make_text_block("Done! The bug is fixed.")]),
        ]
        path = write_jsonl(entries)
        assert JsonlParser.get_session_state(str(path)) == "waiting_input"


# ---------------------------------------------------------------------------
# JsonlParser.find_session_jsonl
# ---------------------------------------------------------------------------
class TestFindSessionJsonl:
    def test_single_jsonl_with_conversation(self, tmp_path, monkeypatch):
        """Single JSONL in the project dir with a conversation returns it."""
        project_dir = tmp_path / ".claude" / "projects" / "-tmp-test-project"
        project_dir.mkdir(parents=True)
        jsonl_path = project_dir / "abc123.jsonl"
        jsonl_path.write_text(json.dumps(make_user_entry("hello")) + "\n")

        # Monkeypatch get_project_dir to return our temp directory
        monkeypatch.setattr(
            JsonlParser,
            "get_project_dir",
            staticmethod(lambda cwd: project_dir),
        )

        result = JsonlParser.find_session_jsonl("/tmp/test-project", 0)
        assert result == jsonl_path

    def test_single_jsonl_without_conversation(self, tmp_path, monkeypatch):
        """Single JSONL with no conversation content returns None."""
        project_dir = tmp_path / ".claude" / "projects" / "-tmp-test-project"
        project_dir.mkdir(parents=True)
        jsonl_path = project_dir / "abc123.jsonl"
        jsonl_path.write_text(
            json.dumps({"type": "system", "message": {"role": "system", "content": "x"}})
            + "\n"
        )

        monkeypatch.setattr(
            JsonlParser,
            "get_project_dir",
            staticmethod(lambda cwd: project_dir),
        )

        result = JsonlParser.find_session_jsonl("/tmp/test-project", 0)
        assert result is None

    def test_nonexistent_project_dir(self, tmp_path, monkeypatch):
        """If project dir doesn't exist, returns None."""
        nonexistent = tmp_path / "no-such-dir"
        monkeypatch.setattr(
            JsonlParser,
            "get_project_dir",
            staticmethod(lambda cwd: nonexistent),
        )

        result = JsonlParser.find_session_jsonl("/nonexistent", 0)
        assert result is None

    def test_empty_project_dir(self, tmp_path, monkeypatch):
        """Project dir exists but has no JSONL files returns None."""
        project_dir = tmp_path / ".claude" / "projects" / "-tmp-empty"
        project_dir.mkdir(parents=True)

        monkeypatch.setattr(
            JsonlParser,
            "get_project_dir",
            staticmethod(lambda cwd: project_dir),
        )

        result = JsonlParser.find_session_jsonl("/tmp/empty", 0)
        assert result is None

    def test_multiple_jsonl_with_history_match(self, tmp_path, monkeypatch):
        """Multiple JSONL files with history.jsonl finds the one matching process time."""
        import time

        project_dir = tmp_path / ".claude" / "projects" / "-tmp-multi"
        project_dir.mkdir(parents=True)

        process_create_time = 1700000000.0

        # Create two JSONL files
        uuid1 = "session-aaa"
        uuid2 = "session-bbb"
        path1 = project_dir / f"{uuid1}.jsonl"
        path2 = project_dir / f"{uuid2}.jsonl"
        path1.write_text(json.dumps(make_user_entry("old session")) + "\n")
        path2.write_text(json.dumps(make_user_entry("new session")) + "\n")

        # Create history.jsonl
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(exist_ok=True)
        history_path = claude_dir / "history.jsonl"

        # session-aaa started long before process
        # session-bbb started within 30s of process creation
        history_entries = [
            {"sessionId": uuid1, "timestamp": 1699990000 * 1000},
            {"sessionId": uuid2, "timestamp": int((process_create_time + 5) * 1000)},
        ]
        history_path.write_text(
            "\n".join(json.dumps(e) for e in history_entries) + "\n"
        )

        monkeypatch.setattr(
            JsonlParser,
            "get_project_dir",
            staticmethod(lambda cwd: project_dir),
        )
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

        result = JsonlParser.find_session_jsonl("/tmp/multi", process_create_time)
        assert result == path2
