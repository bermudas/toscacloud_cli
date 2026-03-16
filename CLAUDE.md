# TOSCA Cloud CLI — Project Guide for Claude

## What this project is

A Python CLI (`tosca_cli.py`) for Tricentis TOSCA Cloud REST APIs. Single-file, no hidden packages.
Covers: Identity, MBT/Builder v2 (test cases, modules, reuseable blocks), Playlists v2, Inventory v3 + v1 (undocumented folder ops), Simulations v1.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill in your credentials
python tosca_cli.py config test
```

Config and token cache live in the project directory (`.env`, `token.json`) — never in `~/.tosca_cli`.

## Architecture

Single file, no sub-packages:
- `ToscaClient` class — all HTTP calls, one method per API endpoint. URL builders: `identity()`, `mbt()`, `playlist()`, `inventory_url()`, `inventory_v1_url()`, `simulations_url()`.
- Typer sub-apps: `config_app`, `identity_app`, `cases_app`, `modules_app`, `blocks_app`, `playlists_app`, `inventory_app`, `simulations_app`.
- `_get_access_token()` — OAuth2 client_credentials, token cached in `token.json` (0600), auto-refreshed 60 s before expiry.
- `_output_json()` — Rich syntax-highlighted JSON when stdout is a tty, plain `print(raw)` otherwise (for piping). Place `--json` **before** positional args.
- `_generate_ulid()` — Crockford base32 ULID generator, used for fresh IDs in block parameters and test case step references.

## Key patterns

**Always discover before acting** — the MBT API has no list endpoint. Use Inventory as the discovery layer:
```bash
python tosca_cli.py inventory search "<name>" --type TestCase --json
python tosca_cli.py cases get --json <caseId>          # ground-truth metadata
python tosca_cli.py cases steps <caseId>               # step tree with all module/attr IDs
```

**Block IDs** — `inventory search --type Module` returns module entity IDs, not block IDs. Get block IDs from a test case: `cases get --json <caseId>` → `testCaseItems[].reusableTestStepBlockId` where `$type == "TestStepFolderReferenceV2"`.

**`--json` flag** — must go before positional arguments: `cases get --json <id>` ✓. Using `--` separator causes Typer to treat `--json` as a positional, silently falling back to Rich output.

**Inventory PATCH vs MBT PATCH** — two different formats:
- Inventory v3 PATCH: `{"operations": [{"op": "Replace", ...}]}` (wrapper object, PascalCase op)
- MBT builder PATCH: `[{"op": "replace", ...}]` (bare array, lowercase op)

**Inventory search operators** — despite swagger showing PascalCase (`Contains`, `And`), the live API only accepts lowercase: `contains`, `and`.

**Test case assembly** — when building new cases, always clone an existing one as a template. Each `TestStepFolderReferenceV2` needs a fresh `parameterLayerId` (ULID) and each parameter entry needs `referencedParameterId` pointing to the block's `businessParameter.id`.

## Running a quick smoke test

```bash
python tosca_cli.py config test
python tosca_cli.py inventory search "login" --type TestCase
python tosca_cli.py playlists list
```

## Adding a new CLI command

1. Add a `ToscaClient` method with a docstring: HTTP verb, endpoint path, return type.
2. Add a Typer command on the relevant `*_app` with `--json` flag and Rich output.
3. Update `README.md` Command Reference section.
4. If it exposes a new API quirk, add a row to the Known API Limitations table in `README.md`.

## Files

| File | Purpose |
|------|---------|
| `tosca_cli.py` | Entire CLI — `ToscaClient` + all Typer commands |
| `.env` / `.env.example` | Credentials (`.env` is gitignored) |
| `token.json` | Cached OAuth2 token (gitignored) |
| `requirements.txt` | Runtime dependencies |
| `swaggers/` | Tenant-specific swagger exports for reference (gitignored) |
| `README.md` | User-facing docs |
| `CLAUDE.md` | This file — project guide for Claude Code |
| `.github/agents/tosca.agent.md` | TOSCA Automation agent instructions (full reference: decision tree, CLI commands, caveats, Web + SAP how-to) |
| `tosca-automation/SKILL.md` | Agent Skills package (agentskills.io spec) — condensed skill with links to references/ |
| `tosca-automation/references/web-automation.md` | Html engine how-to (module structure, standard module IDs, Playwright discovery, 4-folder pattern) |
| `tosca-automation/references/sap-automation.md` | SapEngine how-to (standard module IDs, Precondition block, RelativeId patterns, ControlFlowItemV2) |

## Dependencies (requirements.txt)

`httpx`, `typer[all]`, `rich`, `python-dotenv` — no ORM, no frameworks.
