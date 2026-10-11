"""Model-agnostic task state: the things a transcript can't carry over."""
import json
import subprocess
from pathlib import Path

DIR = ".ctxrelay"
LISTS = ("constraint", "decision", "rejected", "hypothesis", "open", "next")
KINDS = ("goal",) + LISTS


def root() -> Path:
    return Path.cwd()


def home() -> Path:
    d = root() / DIR
    d.mkdir(exist_ok=True)
    return d


def load() -> dict:
    p = home() / "state.json"
    base = {"goal": "", **{k: [] for k in LISTS}}
    if p.exists():
        base.update(json.loads(p.read_text()))
    return base


def save(state: dict) -> None:
    (home() / "state.json").write_text(json.dumps(state, indent=2))


def git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def ensure_base() -> None:
    """Remember the commit the task started from, so a handoff can show everything done since."""
    s = load()
    if not s.get("base_sha") and git_head():
        s["base_sha"] = git_head()
        save(s)


def add_note(kind: str, text: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    ensure_base()
    s = load()
    if kind == "goal":
        s["goal"] = text
    else:
        s[kind].append(text)
    save(s)
    return f"recorded {kind}: {text}"


def drop_note(kind: str, index: int) -> str:
    s = load()
    if kind not in LISTS or not 1 <= index <= len(s[kind]):
        raise ValueError("no such note")
    gone = s[kind].pop(index - 1)
    save(s)
    return f"dropped {kind} #{index}: {gone}"
