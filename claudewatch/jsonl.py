"""JsonlParser — reading/parsing Claude JSONL files."""

import json
import re
from pathlib import Path


class JsonlParser:
    @staticmethod
    def get_project_dir(cwd):
        """Convert a cwd to the Claude projects directory path."""
        project_dir_name = re.sub(r'[^a-zA-Z0-9]', '-', cwd)
        return Path.home() / '.claude' / 'projects' / project_dir_name

    @staticmethod
    def find_session_jsonl(cwd, process_create_time):
        """Find the JSONL file for a specific session by matching process creation time."""
        try:
            projects_base = JsonlParser.get_project_dir(cwd)
            if not projects_base.is_dir():
                return None
            jsonl_files = list(projects_base.glob('*.jsonl'))
            if not jsonl_files:
                return None
            if len(jsonl_files) == 1:
                return jsonl_files[0]

            history_path = Path.home() / '.claude' / 'history.jsonl'
            if not history_path.exists():
                return max(jsonl_files, key=lambda f: f.stat().st_mtime)

            session_first_ts = {}
            with open(history_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    sid = obj.get('sessionId', '')
                    ts = int(obj.get('timestamp', 0)) / 1000
                    if sid and ts and sid not in session_first_ts:
                        session_first_ts[sid] = ts

            jsonl_by_uuid = {f.stem: f for f in jsonl_files}
            best_match = None
            best_diff = float('inf')
            for uuid, path in jsonl_by_uuid.items():
                ts = session_first_ts.get(uuid)
                if ts is None:
                    continue
                diff = ts - process_create_time
                if 0 <= diff < 30 and diff < best_diff:
                    best_diff = diff
                    best_match = path

            return best_match or max(jsonl_files, key=lambda f: f.stat().st_mtime)
        except Exception:
            return None

    @staticmethod
    def get_conversation_title(jsonl_path):
        """Get the conversation title (first user text message) from the JSONL."""
        try:
            if not jsonl_path:
                return None
            with open(jsonl_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    msg = obj.get('message', {})
                    if msg.get('role') == 'user':
                        content = msg.get('content', '')
                        if isinstance(content, str) and content.strip():
                            return content.strip()
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get('type') == 'text' and block.get('text', '').strip():
                                    return block['text'].strip()
        except Exception:
            pass
        return None

    @staticmethod
    def get_latest_response(jsonl_path):
        """Get the latest assistant text response from the JSONL."""
        try:
            if not jsonl_path:
                return None
            with open(jsonl_path, 'rb') as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 50000))
                tail = f.read().decode('utf-8', errors='replace')
            for line in reversed(tail.splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = obj.get('message', {})
                if msg.get('role') == 'assistant':
                    for block in msg.get('content', []):
                        if block.get('type') == 'text' and block.get('text', '').strip():
                            return block['text'].strip()
        except Exception:
            pass
        return None

    @staticmethod
    def get_session_state(jsonl_str):
        """Determine the current state of a session by parsing JSONL content.

        Returns one of:
        - 'waiting_tool': Last assistant block is tool_use — waiting for approval
        - 'waiting_input': Last assistant block is text — waiting for next prompt
        - 'active': Claude is working (thinking, executing tools, processing results)
        - 'unknown': Can't determine state
        """
        try:
            if not jsonl_str:
                return 'unknown'
            jsonl_path = Path(jsonl_str)
            if not jsonl_path.exists():
                return 'unknown'

            with open(jsonl_path, 'rb') as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 10000))
                tail = f.read().decode('utf-8', errors='replace')

            for line in reversed(tail.splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = obj.get('type')

                if entry_type == 'progress':
                    return 'active'

                msg = obj.get('message', {})
                role = msg.get('role')
                content = msg.get('content', [])

                if role == 'user':
                    return 'active'

                if role == 'assistant':
                    if isinstance(content, list) and content:
                        block = content[0]
                        if isinstance(block, dict):
                            block_type = block.get('type')
                            if block_type == 'tool_use':
                                return 'waiting_tool'
                            if block_type == 'text':
                                return 'waiting_input'
                            if block_type == 'thinking':
                                return 'active'
                    return 'unknown'

        except Exception:
            pass
        return 'unknown'
