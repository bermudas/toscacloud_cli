# Tosca Commander CLI — 10-minute trial

Goal: confirm the new on-prem CLI can read your workspace, then **round-trip an existing TestCase + Module as new copies** — proving the create flow and cross-object reference rewriting both work end-to-end.

You only need one file: `tosca_commander_cli.py`. Drop it anywhere, install 4 Python packages, set up `.env`, run the steps, paste outputs back.

**No Python on the test box?** Use the bundled `trial.ps1` instead — self-contained PowerShell 5.1+, reads the same `.env`. The PowerShell trial has its own dedicated brief: `AGENT-BRIEF-COMMANDER-PS-TRIAL.md` (in this same folder). It's written for an LLM agent driving the trial on the tester's machine — but a human tester can follow it just as well.

## What this trial does (and doesn't do)

**Does**: reads two existing objects from your workspace (one TestCase + one Module it references), then writes **two new objects** alongside them with `_v2` and `_clone` suffixes — wiring the new TestCase to point at the new Module instead of the original.

**Doesn't**: no modifications or deletes to existing artifacts, no test execution, no permission/workspace-setting changes. Worst-case footprint is two extra named objects in your workspace, which you can remove afterwards with `python tosca_commander_cli.py objects delete <UniqueId>`.

## Prerequisites

- Python 3.10 or newer
- Network access to your Tosca Server
- A workspace name + one auth combo (PAT recommended)

## Setup (3 minutes)

1. Put `tosca_commander_cli.py` into any folder and `cd` there.

2. Install the 4 dependencies:

   ```
   pip install httpx typer rich python-dotenv
   ```

3. Copy the supplied `.env.commander.example` to `.env` and fill in your values:

   ```
   cp .env.commander.example .env
   # then edit .env: set TOSCA_COMMANDER_BASE_URL, TOSCA_COMMANDER_WORKSPACE,
   # and exactly one auth combo (PAT, Basic/AD, OAuth2, Negotiate, or NTLM).
   ```

   PowerShell equivalent: `Copy-Item .env.commander.example .env; notepad .env`

## Trial (5 minutes — please send back every numbered step's output)

### Phase 1: discovery

```
1.  python tosca_commander_cli.py config test
2.  python tosca_commander_cli.py search tql '=>SUBPARTS:TestCase'
3.  python tosca_commander_cli.py search tql '=>SUBPARTS:Module'
```

Pick **one TestCase that uses Module references** — note its `UniqueId` as **TC_OLD** and its parent's `UniqueId` as **TC_PARENT**.
Pick **one Module that the TestCase actually references** — note its `UniqueId` as **MOD_OLD** and its parent's `UniqueId` as **MOD_PARENT**.

### Phase 2: capture the bodies

```
4.  python tosca_commander_cli.py objects get <TC_OLD>  --depth 5
5.  python tosca_commander_cli.py objects get <MOD_OLD> --depth 3
```

Step 4's response should mention `<MOD_OLD>` somewhere (a `OwnerModuleReference` or similar field). That's the link we'll rewrite.

```
6.  python tosca_commander_cli.py objects get <TC_OLD>  --depth 5 > tc.json
7.  python tosca_commander_cli.py objects get <MOD_OLD> --depth 3 > mod.json
```

### Phase 3: round-trip — recreate the Module first, then the TestCase pointing at the new Module

```
8.  python tosca_commander_cli.py objects create <MOD_PARENT> --json-file mod.json \
      --strip-server-fields --rename-suffix "_v2" --show-body
```

Response contains the new Module's `UniqueId`. **Note it as MOD_NEW.**

```
9.  python tosca_commander_cli.py objects create <TC_PARENT> --json-file tc.json \
      --strip-server-fields --rename-suffix "_clone" \
      --rewrite-ref <MOD_OLD>=<MOD_NEW>

10. python tosca_commander_cli.py task workspace CheckInAll
```

### Phase 4: verify persistence

```
11. python tosca_commander_cli.py search tql '=>SUBPARTS:TestCase[Name="<original-name>_clone"]'
12. python tosca_commander_cli.py search tql '=>SUBPARTS:Module[Name="<original-name>_v2"]'
```

Steps 11 and 12 should each return exactly one record — proof both writes persisted past `CheckInAll`.
The TestCase from step 11 should reference `MOD_NEW`, not `MOD_OLD`.

## What the flags do (just so the steps make sense)

| Flag | Effect |
|---|---|
| `--strip-server-fields` | Recursively removes server-minted keys (`UniqueId`, `Revision`, `CreatedBy`/`At`, `ModifiedBy`/`At`, `NodePath`) from the body before POST. Required when you POST back a body fetched via `objects get`. Reference fields like `OwnerModuleReference` are intentionally NOT stripped. |
| `--rename-suffix STR` | Appends `STR` to the root object's `Name` so it doesn't collide with the source object inside the same parent. |
| `--rewrite-ref OLD=NEW` | Repeatable. Recursively replaces any string value equal to `OLD` with `NEW` anywhere in the body. Used to swap the TestCase's module reference from the source Module to the freshly created copy. |
| `--show-body` | Prints the post-transformation body to stderr before POSTing — useful for verifying. |

## What to send back

Paste every step's output (sanitize tokens / customer names). The most important responses for tuning:

- Step 1 — auth handshake + Tosca Server version
- Step 4 — TestCase shape (keys + reference fields are what I need; values can be redacted)
- Step 8 — Module create response, **even if it failed** (the error message tells us which fields to handle differently)
- Step 9 — TestCase create response with the rewritten reference
- Step 11 + 12 — persistence confirmation
- Auth mode that worked (PAT / basic / negotiate / …)
- Tosca Server version (top of step-1 output)

If any step errors out, paste the full error too — I can't fix what I can't see.
