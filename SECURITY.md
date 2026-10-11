# Security

ctxrelay runs locally. It makes no network calls (a test enforces this), stores its state in `.ctxrelay/` inside your
project, and reads session transcripts under `~/.claude/projects` and `~/.codex/sessions` only to recover edits and
test runs for the current project. It never touches OAuth tokens or credentials.

Things worth knowing:
- `.ctxrelay/events.jsonl` and `HANDOFF.md` can contain command lines and the tail of command output. `ctxrelay init`
  adds `.ctxrelay/` to your `.gitignore` so it is not committed; keep it out of anything you share.
- `ctxrelay init --hooks` edits `.claude/settings.json` in the project to add two hooks that run `ctxrelay record`.

To report a vulnerability, use GitHub's private "Report a vulnerability" button on the Security tab of
https://github.com/JyotBuch/ctxrelay rather than a public issue.
