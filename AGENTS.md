# AGENTS.md — How agents should work in this repo

This file is a tool-agnostic entry point for any AI coding agent. It tells you what this project is, how to operate it, and where the deeper guidance lives.

## What this project is

A single-file Python CLI (`tosca_cli.py`) for the Tricentis TOSCA Cloud REST APIs. Covers: Identity, MBT/Builder v2 (test cases, modules, reusable blocks), Playlists v2, Inventory v3 + v1 (undocumented folder ops), Simulations v1, E2G (execution logs).

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in TOSCA_TENANT_URL, TOSCA_SPACE_ID, client creds
python tosca_cli.py config test # verify
```

Config lives at `.env` in the project root. Token cache at `./token.json`. Never under `~/.tosca_cli/`.

## Core operating principles

1. **Discover before acting** — the MBT API has no list endpoint. Start with `inventory search` to resolve IDs, then use `cases get`/`cases steps`/`modules get` as ground truth before building a new artifact.
2. **Match IDs carefully** — MBT endpoints want the Inventory `entityId` (e.g. `WcucATcH0UKiiL9aoQsJyg`); the playlist item's `id` and `attributes.surrogate` UUID both 404 against MBT. Always resolve via `inventory search --type TestCase --json` → `id.entityId`.
3. **Prefer editing existing files** over creating new ones. Don't add features/refactors beyond what the task requires.
4. **On personal-agent runs, use MCP not the CLI** — the service token is 403'd on private runs (see `.github/copilot-instructions.md` or `CLAUDE.md` for the polling recipe).
5. **Confirm every write by GET + version bump** — CLI `✓ patched`, HTTP 204, or `{}` only prove the request shape was accepted, NOT that the diff landed. MBT PATCH silently drops unsupported ops (deep JSON-pointer paths, `remove` on array elements, `move`). After every `cases patch` / `cases update` / `modules update` / `blocks update` / `inventory patch`, GET the artifact and assert (a) `version` bumped and (b) the edited field actually changed. If it didn't, fall back to full PUT.
6. **Read the skill references before mutating** — the standard-modules / web-automation references in `.claude/skills/tosca-automation/references/` list known silent-failure modes (e.g. `"` in JS values, `{MOUSEOVER}` crossing mega-menu triggers, Verify-in-If hard-fails on missing documents). Cross-referencing before you edit saves full re-run cycles.

## Where detailed guidance lives

Read these in order depending on the task:

| Task | Start here |
|------|-----------|
| Any TOSCA CLI operation | Skill: `.claude/skills/tosca-automation/SKILL.md` |
| Web (Html engine) test case | `.claude/skills/tosca-automation/references/web-automation.md` |
| SAP GUI test case | `.claude/skills/tosca-automation/references/sap-automation.md` |
| Reusable blocks | `.claude/skills/tosca-automation/references/blocks.md` |
| Real-mouse CDP browser inspection | Skill: `.claude/skills/browser-verify/SKILL.md` |
| API quirks reference | `.github/copilot-instructions.md` (table of runtime caveats) |
| Tool-specific configuration | `CLAUDE.md` (Claude Code), `.github/copilot-instructions.md` (Copilot) |

Skills at `.claude/skills/` follow the open [agentskills.io](https://agentskills.io) spec and are auto-discovered by Claude Code, GitHub Copilot (CLI + VS Code), Cursor, Gemini CLI, OpenAI Codex, and other compatible agents.

## Quick smoke test

```bash
python tosca_cli.py config test
python tosca_cli.py inventory search "login" --type TestCase
python tosca_cli.py playlists list
```

## Adding a new CLI command

1. Add a `ToscaClient` method with a docstring: HTTP verb, endpoint path, return type.
2. Add a Typer command to the relevant `*_app` with a `--json` flag and Rich output.
3. Update `README.md` Command Reference.
4. If it exposes a new API quirk, add a row to the caveats table in `.github/copilot-instructions.md` and the Skill caveats table.
