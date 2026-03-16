# Contributing to TOSCA Cloud CLI

Contributions are welcome! This project follows the standard GitHub fork-and-pull-request workflow.

## How to contribute

### 1. Fork and clone

1. Click **Fork** on the [GitHub repository](https://github.com/bermudas/toscacloud_cli) to create your copy.
2. Clone your fork locally:
   ```bash
   git clone https://github.com/<your-username>/toscacloud_cli.git
   cd toscacloud_cli
   ```
3. Add the upstream remote so you can pull future changes:
   ```bash
   git remote add upstream https://github.com/bermudas/toscacloud_cli.git
   ```

### 2. Set up your environment

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your own TOSCA Cloud credentials
python tosca_cli.py config test
```

### 3. Make your changes

- Work on a feature branch, not `main`:
  ```bash
  git checkout -b feature/my-new-command
  ```
- Keep changes focused — one feature or fix per pull request.
- Follow the existing code style (see [copilot-instructions.md](.github/copilot-instructions.md)):
  - One `ToscaClient` method per API endpoint, with a docstring (`VERB /path → ReturnType`)
  - Every Typer command needs a `--json` flag and Rich table/panel output
  - Use `_output_json()`, `_exit_err()`, `_generate_ulid()` — don't reinvent them
- If you discover a new API quirk, add it to the **Known API Limitations** table in `README.md`.

### 4. Test your changes

There is no automated test suite (the API requires a live tenant). Smoke-test manually:

```bash
python tosca_cli.py config test
python tosca_cli.py <your-new-command> --help
python tosca_cli.py <your-new-command> [args]   # against your own tenant
```

### 5. Keep your fork up to date

Before opening a PR, rebase onto the latest upstream `main`:

```bash
git fetch upstream
git rebase upstream/main
```

### 6. Open a pull request

Push your branch to your fork and open a pull request against `bermudas/toscacloud_cli:main`.

In the PR description, include:
- What API endpoint / use case the change covers
- Example command(s) showing the new behaviour
- Any new API quirks discovered (if applicable)

## What makes a good contribution

| Good fit | Not a good fit |
|---|---|
| New CLI commands for undiscovered API endpoints | Rewriting existing commands without a concrete reason |
| Bug fixes with a repro case | Changes that require a specific tenant configuration |
| Documentation improvements | Adding heavy dependencies (keep it `httpx` + `typer` + `rich`) |
| New API quirk discoveries | Breaking changes to existing command signatures |

## Questions?

Open a [GitHub Issue](https://github.com/bermudas/toscacloud_cli/issues) to discuss an idea before building it — saves everyone time.
