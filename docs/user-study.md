# User study protocol (10-20 developers who use both Claude Code and Codex CLI)

Goal: find out whether people need this, not to sell it. Say that up front. Never ask for code or private repo content.

## Day 0: install (15 minutes, screen share or async screen recording)
Give them only the README link. Do not help unless they are stuck for 2 minutes; write down where.
Record: minutes from start to a working `ctxrelay` status screen, every error or hesitation, whether they ran
`ctxrelay doctor`, whether they installed the hooks and MCP server.

## First real switch (they do this when a limit hits or they choose to)
Ask them to run `ctxrelay switch <other CLI>` and then answer:
1. Did the new session continue correctly without you re-explaining? (yes / mostly / no)
2. What did it not know that it should have? (paste the missing fact, not code)
3. Was anything in the switch summary wrong or confusing?
4. How long did the switch take compared with what you did before?
Optional: paste `ctxrelay doctor` output and the "Verified work" section of `.ctxrelay/HANDOFF.md`, private parts removed.

## Day 7
1. Still installed? How many switches since day 0?
2. What would you lose if you uninstalled it today? (the key question; "nothing" is a valid answer)
3. What did you stop using? What did you wish it did?
4. Would you tell a colleague about it? Why or why not?

## Log (one row per person, kept in a private sheet)
person id | CLIs used | install minutes | blockers | first switch outcome | missing facts | switches in week 1 | still using day 7 | "lose if uninstalled" quote

## Decision gates (set before looking at data)
- Keep investing if at least 50% finish the first switch unaided, at least 30% still use it on day 7, and most "mostly/yes" answers.
- Narrow the product if people value only the handoff file.
- Stop or pivot if almost nobody keeps it, or the CLIs ship a cross-provider handoff themselves.
