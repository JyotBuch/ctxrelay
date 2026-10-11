"""Verified work: what was actually edited, run and observed, captured without relying on the model.

Events are appended to `.ctxrelay/events.jsonl` by `ctxrelay record` (a Claude Code hook) or recovered later
from session transcripts by `ctxrelay ingest`. Transcript formats are undocumented: parsing is best-effort.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from . import state

MAX_FIELD = 400          # chars kept per command / output tail
MAX_EVENTS = 2000        # file is trimmed to the newest events past this
TEST_RE = re.compile(r"\b(pytest|py\.test|unittest|tox|nox|jest|vitest|mocha|go test|cargo test|cargo nextest|"
                     r"rspec|phpunit|mvn test|gradle test|(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test|"
                     r"make\s+(?:check|test))\b")
FAIL_RE = re.compile(r"\b\d+\s+(?:failed|failures?|errors?)\b|^FAILED\b|^FAIL\b|^--- FAIL|Traceback \(most recent",
                     re.M)
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def path() -> Path:
    return state.home() / "events.jsonl"


def is_test_cmd(cmd: str) -> bool:
    """Only the first line counts: heredocs and commit messages often mention `pytest` without running it."""
    return bool(TEST_RE.search(cmd.strip().split("\n")[0]))


def _tail(text: str, n: int = MAX_FIELD) -> str:
    text = text.strip()
    return text if len(text) <= n else "…" + text[-n:]


def _head(cmd: str, n: int = 160) -> str:
    cmd = cmd.strip().split("\n")[0]
    return cmd if len(cmd) <= n else cmd[:n] + "…"


def _flatten(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_flatten(c.get("text", "") if isinstance(c, dict) else c) for c in content)
    if isinstance(content, dict):
        return "\n".join(str(content.get(k, "")) for k in ("stdout", "stderr", "output", "text") if content.get(k))
    return ""


def _rel(file_path: str) -> str:
    """Path relative to the project, or "" when the file lives outside it (plans, memory files, ...)."""
    p = Path(file_path)
    if not p.is_absolute():
        return file_path
    try:
        return str(p.resolve().relative_to(state.root().resolve()))
    except (ValueError, OSError):
        return ""


def make_event(tool: str, tool_input: dict, output: str, failed: bool, ts: str = "", src: str = "hook"):
    """Turn one tool call into an event dict, or None if it is not worth recording."""
    ts = ts or time.strftime("%Y-%m-%dT%H:%M:%S")
    if tool in EDIT_TOOLS:
        f = _rel(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        return {"ts": ts, "kind": "edit", "file": f, "src": src} if f else None
    if tool == "Bash" or tool == "shell":
        cmd = tool_input.get("command") or tool_input.get("cmd") or ""
        if isinstance(cmd, list):
            cmd = " ".join(cmd)
        if not cmd:
            return None
        if is_test_cmd(cmd):
            ok = not failed and not FAIL_RE.search("\n".join(output.strip().splitlines()[-12:]))
            return {"ts": ts, "kind": "test", "cmd": _head(cmd), "ok": ok,
                    "summary": _tail(output), "src": src}
        if failed:
            return {"ts": ts, "kind": "error", "cmd": _head(cmd), "summary": _tail(output), "src": src}
    return None


def append(events) -> int:
    events = [e for e in events if e]
    if not events:
        return 0
    p = path()
    seen = {e.get("id") for e in read() if e.get("id")}
    fresh = [e for e in events if not e.get("id") or e["id"] not in seen]
    if not fresh:
        return 0
    with p.open("a") as fh:
        for e in fresh:
            fh.write(json.dumps(e) + "\n")
    lines = p.read_text().splitlines()
    if len(lines) > MAX_EVENTS:
        p.write_text("\n".join(lines[-MAX_EVENTS:]) + "\n")
    return len(fresh)


def read() -> list:
    p = path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _find_project_root(start: Path) -> Path:
    for d in (start, *start.parents):
        if (d / state.DIR).is_dir():
            return d
    return start


def record_hook(payload: dict) -> int:
    """Handle one Claude Code PostToolUse / PostToolUseFailure payload. Never raises."""
    try:
        os.chdir(_find_project_root(Path(payload.get("cwd") or os.getcwd())))
        failed = payload.get("hook_event_name") == "PostToolUseFailure"
        resp = payload.get("tool_response", payload.get("error", ""))
        if isinstance(resp, dict) and resp.get("interrupted"):
            failed = True
        ev = make_event(payload.get("tool_name", ""), payload.get("tool_input") or {}, _flatten(resp), failed)
        return append([ev])
    except Exception:
        return 0


# --- transcript fallback -------------------------------------------------

def _claude_events(file: Path) -> list:
    calls, out = {}, []
    for line in file.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        content = (d.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                calls[b.get("id")] = (b.get("name", ""), b.get("input") or {}, d.get("timestamp", ""))
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in calls:
                name, inp, ts = calls[b["tool_use_id"]]
                text = _flatten(b.get("content"))
                failed = bool(b.get("is_error")) or text.startswith("Exit code")
                ev = make_event(name, inp, text, failed, ts, src="transcript")
                if ev:
                    ev["id"] = b["tool_use_id"]
                    out.append(ev)
    return out


CMD_RE = re.compile(r"""cmd\s*:\s*("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')""")
PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", re.M)
EXIT_RE = re.compile(r"(?:exit(?:ed)?(?: with)? code|Process exited with code)\s*:?\s*(-?\d+)", re.I)


def _codex_events(file: Path) -> list:
    calls, out = {}, []
    for line in file.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        p = d.get("payload") or {}
        t = p.get("type")
        if t in ("function_call", "custom_tool_call"):
            raw = p.get("arguments") if t == "function_call" else p.get("input")
            cmd, patch_text = "", str(raw or "")
            try:
                args = json.loads(str(raw)) if t == "function_call" else {}
                cmd = args.get("cmd") or args.get("command") or ""
                if isinstance(cmd, list):
                    cmd = " ".join(cmd)
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
            if not cmd:
                m = CMD_RE.search(patch_text)
                if m:
                    try:
                        cmd = json.loads(m.group(1)) if m.group(1)[0] == '"' else m.group(1)[1:-1]
                    except json.JSONDecodeError:
                        cmd = m.group(1)[1:-1]
            calls[p.get("call_id")] = (cmd, patch_text, d.get("timestamp", ""))
        elif t in ("function_call_output", "custom_tool_call_output") and p.get("call_id") in calls:
            cmd, raw, ts = calls[p["call_id"]]
            text = _flatten(p.get("output"))
            for f in PATCH_FILE_RE.findall(raw):
                out.append({"ts": ts, "kind": "edit", "file": f.strip(), "src": "transcript",
                            "id": f"{p['call_id']}:{f}"})
            m = EXIT_RE.search(text)
            failed = bool(m and m.group(1) != "0")
            ev = make_event("shell", {"cmd": cmd}, text, failed, ts, src="transcript") if cmd else None
            if ev:
                ev["id"] = p["call_id"]
                out.append(ev)
    return out


def _codex_session_cwd(file: Path) -> str:
    try:
        with file.open() as fh:
            return str((json.loads(fh.readline()).get("payload") or {}).get("cwd", ""))
    except (OSError, json.JSONDecodeError):
        return ""


def session_files(home: Path | None = None, cwd: Path | None = None) -> list:
    """Newest-first (source, file) pairs of transcripts belonging to this project."""
    home = home or Path.home()
    cwd = (cwd or state.root()).resolve()
    found = []
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    for f in (home / ".claude" / "projects" / slug).glob("*.jsonl"):
        found.append(("claude", f))
    codex = home / ".codex" / "sessions"
    if codex.is_dir():
        recent = sorted(codex.rglob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)[:40]
        found += [("codex", f) for f in recent if _codex_session_cwd(f) == str(cwd)]
    return sorted(found, key=lambda sf: sf[1].stat().st_mtime, reverse=True)


def ingest(home: Path | None = None, limit: int = 1) -> int:
    """Recover events from the newest `limit` transcript(s) of this project. Idempotent (dedupes by id)."""
    added = 0
    for src, f in session_files(home)[:limit]:
        try:
            added += append(_claude_events(f) if src == "claude" else _codex_events(f))
        except Exception:
            continue
    return added


# --- summary for the handoff ---------------------------------------------

def summarize() -> dict:
    evs = read()
    edited = list(dict.fromkeys(e["file"] for e in evs if e.get("kind") == "edit" and e.get("file")))
    tests = [e for e in evs if e.get("kind") == "test"]
    errors = [e for e in evs if e.get("kind") == "error"]
    return {"edited": edited, "tests": tests, "errors": errors, "count": len(evs)}
