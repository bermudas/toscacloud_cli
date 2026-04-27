#!/usr/bin/env python3
"""
tosca_commander_cli.py – CLI for Tricentis TOSCA Commander REST API (on-prem)

Wraps the Tosca Commander REST Webservice (TCRS) — the workspace-scoped REST
service hosted by `Tricentis.Tosca.RestApiService` at /rest/toscacommander/.
Use this CLI for on-prem Tosca workspaces; use `tosca_cli.py` (sibling file)
for Tosca Cloud (multi-tenant SaaS).

API surfaces (filling in across milestones):
  config      — connection settings, version probe, auth dry-run
  workspace   — open / info / projectid (M2)
  objects     — get / create / update / delete (M2)
  meta        — discover available object types and their tasks (M2)
  search      — TQL queries via `/object/<id>/task/search` (M3)
  task        — execute object or generic workspace tasks (M3)
  files       — list / download attached files (M4)
  approvals   — pre-execution approval workflow (M4)
  logs        — walk ExecutionLog → Subparts (M4)

Auth modes (pluggable, env-var driven):
  Basic                   TOSCA_COMMANDER_USER + TOSCA_COMMANDER_PASSWORD
  PAT                     TOSCA_COMMANDER_TOKEN
  OAuth2 client-creds     TOSCA_COMMANDER_CLIENT_ID + TOSCA_COMMANDER_CLIENT_SECRET
  Negotiate (NTLM/Kerb)   TOSCA_COMMANDER_AUTH=negotiate    [extras: pip install -r requirements-windows-auth.txt]
  NTLM (explicit creds)   TOSCA_COMMANDER_AUTH=ntlm + USER + PASSWORD   [extras: pip install -r requirements-ntlm.txt]

`auto` mode (default) picks the first matching combo: PAT → client-creds → Basic.
Set TOSCA_COMMANDER_AUTH=<mode> to force a specific strategy.

Quick start:
  cp .env.example .env       # fill in TOSCA_COMMANDER_BASE_URL + auth vars
  python tosca_commander_cli.py config test
  python tosca_commander_cli.py config test --workspace MyWorkspace
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

# ---------------------------------------------------------------------------
# Bootstrap: load settings from .env in the project directory
# ---------------------------------------------------------------------------
_CLI_DIR = Path(__file__).parent
load_dotenv(_CLI_DIR / ".env")

console = Console()

# ---------------------------------------------------------------------------
# Typer apps
# ---------------------------------------------------------------------------
app = typer.Typer(
    name="commander",
    help="[bold magenta]CLI[/bold magenta] for Tricentis TOSCA Commander REST API (on-prem)",
    rich_markup_mode="rich",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
config_app     = typer.Typer(help="Connection configuration",                  no_args_is_help=True)
workspace_app  = typer.Typer(help="Workspace lifecycle (open, info, project)", no_args_is_help=True)
objects_app    = typer.Typer(help="Object CRUD (get/create/update/delete)",    no_args_is_help=True)
meta_app       = typer.Typer(help="Discover object types and their tasks",     no_args_is_help=True)
search_app     = typer.Typer(help="TQL search via /object/<id>/task/search",   no_args_is_help=True)
task_app       = typer.Typer(help="Execute tasks on objects or workspace",     no_args_is_help=True)
files_app      = typer.Typer(help="Attached files (list/download)",            no_args_is_help=True)
approvals_app  = typer.Typer(help="Pre-execution approval workflow",           no_args_is_help=True)

app.add_typer(config_app,     name="config")
app.add_typer(workspace_app,  name="workspace")
app.add_typer(objects_app,    name="objects")
app.add_typer(meta_app,       name="meta")
app.add_typer(search_app,     name="search")
app.add_typer(task_app,       name="task")
app.add_typer(files_app,      name="files")
app.add_typer(approvals_app,  name="approvals")


# ---------------------------------------------------------------------------
# Errors and small helpers (mirrors tosca_cli.py conventions)
# ---------------------------------------------------------------------------
class ToscaCommanderError(Exception):
    """Raised when the TCRS API returns a non-2xx response."""
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body}")


def _output_json(data) -> None:
    raw = json.dumps(data, indent=2, default=str)
    if sys.stdout.isatty():
        console.print(Syntax(raw, "json", theme="monokai", line_numbers=False))
    else:
        print(raw)


def _exit_err(msg: str) -> None:
    console.print(f"[bold red]Error:[/bold red] {msg}")
    raise typer.Exit(1)


def _require_env(key: str, hint: str = "") -> str:
    val = os.getenv(key, "").strip()
    if not val:
        msg = f"{key} is not set."
        if hint:
            msg += f" {hint}"
        _exit_err(msg)
    return val


def _normalize_base_url(raw: str) -> str:
    """
    Accept any of these and normalize:
      http://host:1111
      http://host:1111/
      http://host:1111/rest/toscacommander
      http://host:1111/rest/toscacommander/
    """
    u = raw.rstrip("/")
    if u.lower().endswith("/rest/toscacommander"):
        return u
    return f"{u}/rest/toscacommander"


# ---------------------------------------------------------------------------
# Pluggable auth
# ---------------------------------------------------------------------------
AUTH_MODES = ("auto", "basic", "pat", "client-creds", "negotiate", "ntlm")


def _select_auth() -> tuple[httpx.Auth, str]:
    """
    Pick an httpx.Auth based on env vars and the TOSCA_COMMANDER_AUTH override.
    Returns (auth, mode-name) so callers can report which mode is active.
    """
    mode = os.getenv("TOSCA_COMMANDER_AUTH", "auto").lower().strip() or "auto"
    if mode not in AUTH_MODES:
        _exit_err(f"Unknown TOSCA_COMMANDER_AUTH={mode!r}. Allowed: {', '.join(AUTH_MODES)}")

    user = os.getenv("TOSCA_COMMANDER_USER", "").strip()
    password = os.getenv("TOSCA_COMMANDER_PASSWORD", "").strip()
    token = os.getenv("TOSCA_COMMANDER_TOKEN", "").strip()
    cid = os.getenv("TOSCA_COMMANDER_CLIENT_ID", "").strip()
    csecret = os.getenv("TOSCA_COMMANDER_CLIENT_SECRET", "").strip()

    if mode == "negotiate":
        try:
            from requests_negotiate_sspi import HttpNegotiateAuth  # type: ignore
        except ImportError:
            _exit_err(
                "Negotiate auth requires extra deps. Install with:\n"
                "  pip install requests-negotiate-sspi\n"
                "(Windows-only — IIS Windows Authentication uses SSPI.)"
            )
        return _RequestsAuthAdapter(HttpNegotiateAuth()), "negotiate"

    if mode == "ntlm":
        if not user or not password:
            _exit_err("TOSCA_COMMANDER_AUTH=ntlm requires TOSCA_COMMANDER_USER and TOSCA_COMMANDER_PASSWORD.")
        try:
            from httpx_ntlm import HttpNtlmAuth  # type: ignore
        except ImportError:
            _exit_err("NTLM auth requires extra deps. Install with:\n  pip install httpx-ntlm")
        return HttpNtlmAuth(user, password), "ntlm"

    if mode == "pat" or (mode == "auto" and token):
        if not token:
            _exit_err("PAT auth requires TOSCA_COMMANDER_TOKEN.")
        # Tosca PAT: pass token as basic-auth password with empty username.
        return httpx.BasicAuth("", token), "pat"

    if mode == "client-creds" or (mode == "auto" and cid):
        if not cid or not csecret:
            _exit_err(
                "Client-credentials auth requires TOSCA_COMMANDER_CLIENT_ID and TOSCA_COMMANDER_CLIENT_SECRET."
            )
        return _ClientCredentialsAuth(cid, csecret), "client-creds"

    # Default → Basic (also covers AD-backed multi-user workspaces)
    if not user or not password:
        _exit_err(
            "No Tosca Commander credentials configured.\n"
            "Set one of:\n"
            "  TOSCA_COMMANDER_TOKEN                       (PAT)\n"
            "  TOSCA_COMMANDER_USER + _PASSWORD            (Basic / AD)\n"
            "  TOSCA_COMMANDER_CLIENT_ID + _CLIENT_SECRET  (OAuth2 client-credentials)\n"
            "  TOSCA_COMMANDER_AUTH=negotiate              (IIS Windows Auth — needs requests-negotiate-sspi)\n"
            "  TOSCA_COMMANDER_AUTH=ntlm + USER + PASSWORD (explicit-cred NTLM — needs httpx-ntlm)"
        )
    return httpx.BasicAuth(user, password), "basic"


class _RequestsAuthAdapter(httpx.Auth):
    """Adapter so a `requests.auth.AuthBase` (e.g. requests-negotiate-sspi) works under httpx.

    Negotiate/NTLM is challenge-driven: server returns 401 + WWW-Authenticate, we replay.
    """
    requires_response_body = True

    def __init__(self, requests_auth):
        self._auth = requests_auth

    def auth_flow(self, request: httpx.Request):
        response = yield request
        if response.status_code != 401:
            return
        # Build a duck-typed requests-style request the auth handler can sign.
        class _R:
            pass
        r = _R()
        r.headers = dict(request.headers)
        r.url = str(request.url)
        r.body = request.content
        r.method = request.method
        # requests-auth handlers mutate r.headers in place; copy back.
        self._auth(r)
        request.headers.update(r.headers)
        yield request


class _ClientCredentialsAuth(httpx.Auth):
    """OAuth2 client_credentials against Tosca Server's `/tua/connect/token`.

    The token endpoint sits at `<server-root>/tua/connect/token`, which is the
    HTTPS gateway root **above** `/rest/toscacommander`. We derive it from the
    request URL on first use and cache the bearer token until ~30 s before
    expiry.
    """
    requires_response_body = True

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: str | None = None
        self._exp: float = 0.0

    def auth_flow(self, request: httpx.Request):
        if not self._token or time.time() > self._exp - 30:
            base = str(request.url).split("/rest/")[0]
            token_url = f"{base}/tua/connect/token"
            body = (
                f"grant_type=client_credentials&client_id={self.client_id}"
                f"&client_secret={self.client_secret}"
            ).encode()
            tok_req = httpx.Request(
                "POST", token_url,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                content=body,
            )
            tok_resp = yield tok_req
            tok_resp.read()
            if tok_resp.status_code != 200:
                raise RuntimeError(
                    f"OAuth2 token fetch failed: HTTP {tok_resp.status_code} {tok_resp.text[:300]}"
                )
            data = tok_resp.json()
            self._token = data.get("access_token")
            self._exp = time.time() + int(data.get("expires_in", 3600))
            if not self._token:
                raise RuntimeError(f"No access_token in token response: {data}")
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------
class ToscaCommanderClient:
    """HTTP client for Tosca Commander REST API (TCRS).

    Base URL pattern: http(s)://<host>:<port>/rest/toscacommander
    All paths are appended to base_url; workspace operations include
    `<workspace>` as the first path segment.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        auth: Optional[httpx.Auth] = None,
        verify_ssl: bool = True,
        timeout: float = 60.0,
    ):
        raw = base_url or _require_env(
            "TOSCA_COMMANDER_BASE_URL",
            "Example: http://yourhost:1111/rest/toscacommander",
        )
        self.base_url = _normalize_base_url(raw)
        if auth is None:
            self.auth, self.auth_mode = _select_auth()
        else:
            self.auth = auth
            self.auth_mode = "explicit"
        self.verify_ssl = verify_ssl
        self.timeout = timeout

    # ----- HTTP -----------
    def _client(self) -> httpx.Client:
        return httpx.Client(
            auth=self.auth,
            verify=self.verify_ssl,
            timeout=self.timeout,
            headers={"Accept": "application/json"},
        )

    def _check(self, resp: httpx.Response):
        if resp.status_code >= 400:
            raise ToscaCommanderError(resp.status_code, resp.text[:600])
        if not resp.content:
            return {}
        ctype = resp.headers.get("content-type", "")
        if "application/json" in ctype:
            return resp.json()
        return {"raw": resp.text}

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}" if path else self.base_url

    def get(self, path: str = "", params: dict | None = None):
        with self._client() as c:
            return self._check(c.get(self._url(path), params=params))

    def post(self, path: str, body=None, params: dict | None = None):
        with self._client() as c:
            return self._check(c.post(self._url(path), json=body, params=params))

    def put(self, path: str, body):
        with self._client() as c:
            return self._check(c.put(self._url(path), json=body))

    def delete(self, path: str):
        with self._client() as c:
            return self._check(c.delete(self._url(path)))

    # ----- Probes ---------
    def version(self) -> dict:
        """GET <base> with no path → version info (per devcorner `version_information`)."""
        return self.get("")

    def open_workspace(self, workspace: str) -> dict:
        """GET <base>/<workspace> — opens (or attaches to) the workspace."""
        return self.get(workspace)

    # ----- Workspace -----
    def workspace_projectid(self, workspace: str) -> dict:
        """GET <base>/<workspace>/projectid — workspace's project ID."""
        return self.get(f"{workspace}/projectid")

    def workspace_component(self, workspace: str, component: str) -> dict:
        """GET <base>/<workspace>/component/<name> — top-level component folder."""
        return self.get(f"{workspace}/component/{component}")

    def workspace_project_root(self, workspace: str) -> dict:
        """GET <base>/<workspace>/object/project/ — project root object."""
        return self.get(f"{workspace}/object/project/")

    # ----- Objects -------
    def object_get(self, workspace: str, object_id: str, depth: int | None = None) -> dict:
        """GET <base>/<workspace>/object/<id> — object representation."""
        params = {"depth": depth} if depth is not None else None
        return self.get(f"{workspace}/object/{object_id}", params=params)

    def object_create(self, workspace: str, parent_id: str, body: dict) -> dict:
        """POST <base>/<workspace>/object/<parentId> — create child object.

        Body: {"TypeName": "<TypeName>", "Name": "...", "Properties": {...}}.
        """
        return self.post(f"{workspace}/object/{parent_id}", body=body)

    def object_update(self, workspace: str, object_id: str, body: dict) -> dict:
        """PUT <base>/<workspace>/object/<id> — full update."""
        return self.put(f"{workspace}/object/{object_id}", body=body)

    def object_delete(self, workspace: str, object_id: str) -> dict:
        """DELETE <base>/<workspace>/object/<id>."""
        return self.delete(f"{workspace}/object/{object_id}")

    def object_tree(self, workspace: str, object_id: str, depth: int = 1) -> dict:
        """GET <base>/<workspace>/object/<id>/tree?depth=N."""
        return self.get(f"{workspace}/object/{object_id}/tree", params={"depth": depth})

    def object_associations(self, workspace: str, object_id: str,
                            assoc_name: str | None = None) -> dict:
        """GET <base>/<workspace>/object/<id>/association[/<name>]."""
        path = f"{workspace}/object/{object_id}/association"
        if assoc_name:
            path += f"/{assoc_name}"
        return self.get(path)

    # ----- Meta info -----
    def meta_list(self, workspace: str) -> dict:
        """GET <base>/<workspace>/meta — list known object types."""
        return self.get(f"{workspace}/meta")

    def meta_for_type(self, workspace: str, type_name: str) -> dict:
        """GET <base>/<workspace>/meta/<TypeName> — type metadata + supported tasks."""
        return self.get(f"{workspace}/meta/{type_name}")

    # ----- TQL search -----
    def tql_search(self, workspace: str, root_id: str, tql: str) -> dict:
        """POST <base>/<workspace>/object/<rootId>/task/search?tqlString=...

        TQL queries can run against any object as the search root. Common roots:
        the project root (use `workspace_project_root` to get it), or any folder.
        POST is used so the (often-long) tqlString lands in the body, not the URL.
        """
        # The Tosca REST surface accepts tqlString as a query parameter even on POST.
        # Falls back to GET if the install rejects the body.
        return self.post(f"{workspace}/object/{root_id}/task/search",
                         params={"tqlString": tql})

    # ----- Task execution -----
    def task_object(self, workspace: str, object_id: str, task_name: str,
                    params: dict | None = None, post: bool = True) -> dict:
        """Execute an object-bound task. POST by default (handles long params + binary)."""
        path = f"{workspace}/object/{object_id}/task/{task_name}"
        if post:
            return self.post(path, params=params)
        return self.get(path, params=params)

    def task_workspace(self, workspace: str, task_name: str,
                       params: dict | None = None, post: bool = True) -> dict:
        """Execute a generic workspace-level task (CheckInAll, UpdateAll, CompactWorkspace, RevertAll)."""
        path = f"{workspace}/task/{task_name}"
        if post:
            return self.post(path, params=params)
        return self.get(path, params=params)

    # ----- Files / attachments -----
    def file_list(self, workspace: str, object_id: str) -> dict:
        """GET <base>/<workspace>/object/<id>/files — file references owned by the object."""
        return self.get(f"{workspace}/object/{object_id}/files")

    def file_get(self, workspace: str, object_id: str, file_id: str,
                 save_to: Path | None = None) -> dict | bytes:
        """GET <base>/<workspace>/object/<id>/files/<fileId> — single file (raw bytes if non-JSON)."""
        url = self._url(f"{workspace}/object/{object_id}/files/{file_id}")
        with self._client() as c:
            resp = c.get(url)
            if resp.status_code >= 400:
                raise ToscaCommanderError(resp.status_code, resp.text[:600])
            ctype = resp.headers.get("content-type", "")
            if save_to is not None:
                save_to.write_bytes(resp.content)
                return {"saved": str(save_to), "bytes": len(resp.content), "content_type": ctype}
            if "application/json" in ctype:
                return resp.json()
            return resp.content

    # ----- Reports -----
    def generate_report(self, workspace: str, object_id: str, report_type: str,
                        params: dict | None = None) -> dict:
        """POST <base>/<workspace>/object/<id>/report/<type>."""
        return self.post(f"{workspace}/object/{object_id}/report/{report_type}", params=params)

    # ----- Approvals -----
    def approval_request(self, workspace: str, object_id: str, body: dict | None = None) -> dict:
        """POST <base>/<workspace>/object/<id>/approval/request."""
        return self.post(f"{workspace}/object/{object_id}/approval/request", body=body or {})

    def approval_give(self, workspace: str, object_id: str, body: dict | None = None) -> dict:
        """POST <base>/<workspace>/object/<id>/approval/give."""
        return self.post(f"{workspace}/object/{object_id}/approval/give", body=body or {})


# ---------------------------------------------------------------------------
# `config` subcommands
# ---------------------------------------------------------------------------

@config_app.command("test")
def config_test(
    workspace: Optional[str] = typer.Option(
        None, "--workspace", "-w", envvar="TOSCA_COMMANDER_WORKSPACE",
        help="Workspace name to probe (otherwise: only the version endpoint).",
    ),
    insecure: bool = typer.Option(
        False, "--insecure", help="Skip SSL certificate verification (testing only)."
    ),
):
    """Verify connection: version probe + (optional) workspace open."""
    client = ToscaCommanderClient(verify_ssl=not insecure)

    console.print(Panel.fit(
        f"[bold]Base URL[/bold] : {client.base_url}\n"
        f"[bold]Auth mode[/bold]: {client.auth_mode}",
        title="Tosca Commander connection",
        border_style="cyan",
    ))

    # 1) Version probe (works without auth on some installs; with auth on others)
    try:
        v = client.version()
        console.print("[green]✓[/green] Version probe OK")
        _output_json(v)
    except ToscaCommanderError as e:
        if e.status == 401:
            _exit_err(
                f"Auth rejected at version probe (HTTP 401). "
                f"Active mode = {client.auth_mode}. Check credentials or set TOSCA_COMMANDER_AUTH."
            )
        _exit_err(f"Version probe failed: HTTP {e.status} – {e.body[:200]}")
    except httpx.RequestError as e:
        _exit_err(
            f"Could not reach {client.base_url}: {e}\n"
            f"Check that Tricentis.Tosca.RestApiService is running on the server "
            f"and the port is reachable from this host."
        )

    # 2) Optional workspace open
    if workspace:
        try:
            w = client.open_workspace(workspace)
            console.print(f"[green]✓[/green] Workspace [bold]{workspace}[/bold] opened")
            _output_json(w)
        except ToscaCommanderError as e:
            _exit_err(
                f"Open workspace [bold]{workspace}[/bold] failed: HTTP {e.status} – {e.body[:200]}\n"
                f"Common causes: workspace name typo, workspace not in WorkspaceBasePath, "
                f"insufficient permissions for {client.auth_mode} auth."
            )


@config_app.command("show")
def config_show():
    """Show the current Commander connection settings (credentials redacted)."""
    def mask(key: str) -> str:
        return "[dim]<set>[/dim]" if os.getenv(key) else "[dim](unset)[/dim]"

    rows = [
        ("TOSCA_COMMANDER_BASE_URL",      os.getenv("TOSCA_COMMANDER_BASE_URL", "[red](not set)[/red]")),
        ("TOSCA_COMMANDER_AUTH",          os.getenv("TOSCA_COMMANDER_AUTH", "auto")),
        ("TOSCA_COMMANDER_WORKSPACE",     os.getenv("TOSCA_COMMANDER_WORKSPACE", "[dim](unset)[/dim]")),
        ("TOSCA_COMMANDER_USER",          os.getenv("TOSCA_COMMANDER_USER", "[dim](unset)[/dim]")),
        ("TOSCA_COMMANDER_PASSWORD",      mask("TOSCA_COMMANDER_PASSWORD")),
        ("TOSCA_COMMANDER_TOKEN",         mask("TOSCA_COMMANDER_TOKEN")),
        ("TOSCA_COMMANDER_CLIENT_ID",     mask("TOSCA_COMMANDER_CLIENT_ID")),
        ("TOSCA_COMMANDER_CLIENT_SECRET", mask("TOSCA_COMMANDER_CLIENT_SECRET")),
    ]
    t = Table(title="Tosca Commander Settings", show_header=True,
              header_style="bold cyan", border_style="grey42")
    t.add_column("Key"); t.add_column("Value")
    for k, v in rows:
        t.add_row(k, v)
    console.print(t)


# ---------------------------------------------------------------------------
# Shared option resolvers
# ---------------------------------------------------------------------------

def _ws_or_die(workspace: Optional[str]) -> str:
    """Resolve the workspace name from --workspace or TOSCA_COMMANDER_WORKSPACE."""
    ws = (workspace or os.getenv("TOSCA_COMMANDER_WORKSPACE", "")).strip()
    if not ws:
        _exit_err(
            "Workspace not specified. Pass --workspace/-w or set "
            "TOSCA_COMMANDER_WORKSPACE in .env."
        )
    return ws


def _kv_to_dict(pairs: list[str]) -> dict:
    """Parse `key=value` repeats into a dict (mirrors tosca_cli.py convention)."""
    out: dict = {}
    for raw in pairs:
        if "=" not in raw:
            _exit_err(f"Expected key=value pair, got: {raw!r}")
        k, _, v = raw.partition("=")
        out[k.strip()] = v.strip()
    return out


def _safe_call(label: str, fn, *args, **kwargs):
    """Run an API call and surface a clean error on failure."""
    try:
        return fn(*args, **kwargs)
    except ToscaCommanderError as e:
        _exit_err(f"{label}: HTTP {e.status} – {e.body[:200]}")
    except httpx.RequestError as e:
        _exit_err(f"{label}: connection error – {e}")


# Server-minted fields TCAPI rejects (or silently overwrites) on create POST.
# Stripping them recursively makes a body fetched via `objects get` round-trippable
# back through `objects create`. Reference fields like `OwnerModuleReference` are
# not in this set — they hold *other* objects' UniqueIds and must survive.
SERVER_MINTED_FIELDS: set[str] = {
    "UniqueId", "Revision",
    "CreatedBy", "CreatedAt", "ModifiedBy", "ModifiedAt",
    "NodePath",
}


def _strip_server_fields(obj):
    """Recursively drop server-minted keys from every dict in the tree."""
    if isinstance(obj, dict):
        return {k: _strip_server_fields(v) for k, v in obj.items()
                if k not in SERVER_MINTED_FIELDS}
    if isinstance(obj, list):
        return [_strip_server_fields(x) for x in obj]
    return obj


def _rewrite_refs(obj, mapping: dict[str, str]):
    """Recursively replace any string value equal to a key in `mapping`.

    Used for cross-object reference rewriting — e.g. swapping a TestCase's
    `OwnerModuleReference` from the source Module's UniqueId to the freshly
    created copy's UniqueId.
    """
    if isinstance(obj, dict):
        return {k: _rewrite_refs(v, mapping) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rewrite_refs(x, mapping) for x in obj]
    if isinstance(obj, str) and obj in mapping:
        return mapping[obj]
    return obj


def _parse_rewrite_pairs(pairs: list[str]) -> dict[str, str]:
    """Parse repeated --rewrite-ref OLD=NEW flags into a {OLD: NEW} dict."""
    out: dict[str, str] = {}
    for raw in pairs:
        if "=" not in raw:
            _exit_err(f"--rewrite-ref expects 'OLD=NEW', got: {raw!r}")
        old, _, new = raw.partition("=")
        old, new = old.strip(), new.strip()
        if not old or not new:
            _exit_err(f"--rewrite-ref: empty side in {raw!r}")
        out[old] = new
    return out


# ---------------------------------------------------------------------------
# `workspace` subcommands
# ---------------------------------------------------------------------------

@workspace_app.command("open")
def workspace_open(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
):
    """Open a workspace and print its top-level representation."""
    ws = _ws_or_die(workspace)
    client = ToscaCommanderClient()
    _output_json(_safe_call(f"open {ws}", client.open_workspace, ws))


@workspace_app.command("projectid")
def workspace_projectid(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
):
    """Return the project ID of the workspace."""
    ws = _ws_or_die(workspace)
    client = ToscaCommanderClient()
    _output_json(_safe_call("projectid", client.workspace_projectid, ws))


@workspace_app.command("project-root")
def workspace_project_root(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
):
    """Return the project root object (entry point for tree navigation)."""
    ws = _ws_or_die(workspace)
    client = ToscaCommanderClient()
    _output_json(_safe_call("project-root", client.workspace_project_root, ws))


@workspace_app.command("component")
def workspace_component(
    name: str = typer.Argument(..., help="Component folder name (e.g. Modules, TestCases, Requirements)."),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
):
    """Get a top-level component folder (`Modules`, `TestCases`, etc.) by name."""
    ws = _ws_or_die(workspace)
    client = ToscaCommanderClient()
    _output_json(_safe_call(f"component/{name}", client.workspace_component, ws, name))


# ---------------------------------------------------------------------------
# `objects` subcommands
# ---------------------------------------------------------------------------

@objects_app.command("get")
def objects_get(
    object_id: str = typer.Argument(..., help="UniqueId of the object."),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
    depth: Optional[int] = typer.Option(None, "--depth", "-d",
                                        help="Include child objects up to this depth."),
):
    """GET an object representation by UniqueId."""
    ws = _ws_or_die(workspace)
    client = ToscaCommanderClient()
    _output_json(_safe_call(f"get {object_id}", client.object_get, ws, object_id, depth=depth))


@objects_app.command("create")
def objects_create(
    parent_id: str = typer.Argument(..., help="UniqueId of the parent under which to create."),
    json_file: Path = typer.Option(..., "--json-file", "-f",
                                   help="Path to a JSON body: {\"TypeName\":..., \"Name\":..., \"Properties\":{...}}."),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
    strip_server_fields: bool = typer.Option(
        False, "--strip-server-fields",
        help="Recursively remove server-minted keys (UniqueId, Revision, CreatedBy/At, "
             "ModifiedBy/At, NodePath) from the body before POST. Required when round-tripping "
             "a body fetched via `objects get`.",
    ),
    rename_suffix: Optional[str] = typer.Option(
        None, "--rename-suffix",
        help="Append this string to the root object's Name (e.g. '_clone_v1'). "
             "Useful for round-tripping an existing object as a new sibling without name collision.",
    ),
    rewrite_ref: list[str] = typer.Option(
        [], "--rewrite-ref",
        help="Repeatable: 'OLD=NEW'. Replaces any string value equal to OLD with NEW anywhere "
             "in the body — handles cross-object reference rewriting (e.g. swapping a TestCase's "
             "module reference from the source Module's UniqueId to a freshly created copy's).",
    ),
    show_body: bool = typer.Option(
        False, "--show-body",
        help="Print the post-transformation body to stderr before POSTing. Handy for verifying "
             "--strip / --rename / --rewrite-ref applied as expected.",
    ),
):
    """Create a new object under the given parent. Body shape: TCAPI object representation.

    Round-trip pattern (recreate an existing object as a new sibling):

        objects get <src> --depth 5 > src.json
        objects create <parent> --json-file src.json \\
            --strip-server-fields --rename-suffix "_clone"

    Cross-reference rewrite (e.g. point a recreated TestCase at a freshly created Module copy):

        # 1) recreate the Module first
        objects get <srcModuleId> --depth 3 > mod.json
        objects create <modParent> --json-file mod.json \\
            --strip-server-fields --rename-suffix "_v2"
        # 2) recreate the TestCase, swapping the original module ref to the new one
        objects get <srcTestCaseId> --depth 5 > tc.json
        objects create <tcParent> --json-file tc.json \\
            --strip-server-fields --rename-suffix "_clone" \\
            --rewrite-ref <srcModuleId>=<newModuleId>
    """
    ws = _ws_or_die(workspace)
    if not json_file.exists():
        _exit_err(f"--json-file not found: {json_file}")
    body = json.loads(json_file.read_text())

    if strip_server_fields:
        body = _strip_server_fields(body)
    if rewrite_ref:
        body = _rewrite_refs(body, _parse_rewrite_pairs(rewrite_ref))
    if rename_suffix:
        if not isinstance(body, dict) or "Name" not in body:
            _exit_err("--rename-suffix: body has no top-level 'Name' field.")
        body["Name"] = str(body["Name"]) + rename_suffix

    if show_body:
        console.print("[dim]── post-transformation body ──[/dim]", soft_wrap=False, highlight=False)
        sys.stderr.write(json.dumps(body, indent=2, default=str) + "\n")

    client = ToscaCommanderClient()
    _output_json(_safe_call(f"create under {parent_id}", client.object_create, ws, parent_id, body))


@objects_app.command("update")
def objects_update(
    object_id: str = typer.Argument(..., help="UniqueId of the object to update."),
    json_file: Path = typer.Option(..., "--json-file", "-f",
                                   help="Path to a JSON body with the full updated object representation."),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
):
    """Full PUT update of an object. Always confirm with `objects get` afterwards."""
    ws = _ws_or_die(workspace)
    if not json_file.exists():
        _exit_err(f"--json-file not found: {json_file}")
    body = json.loads(json_file.read_text())
    client = ToscaCommanderClient()
    _output_json(_safe_call(f"update {object_id}", client.object_update, ws, object_id, body))


@objects_app.command("delete")
def objects_delete(
    object_id: str = typer.Argument(..., help="UniqueId of the object to delete."),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
    force: bool = typer.Option(False, "--force", help="Skip confirmation prompt."),
):
    """Delete an object (irreversible). Triggers TCAPI delete on the workspace driver."""
    ws = _ws_or_die(workspace)
    if not force:
        from rich.prompt import Confirm
        if not Confirm.ask(f"[bold red]Delete[/bold red] {object_id} in {ws}?", default=False):
            console.print("[dim]Aborted.[/dim]")
            raise typer.Exit(0)
    client = ToscaCommanderClient()
    _output_json(_safe_call(f"delete {object_id}", client.object_delete, ws, object_id))


@objects_app.command("tree")
def objects_tree(
    object_id: str = typer.Argument(..., help="UniqueId of the object."),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
    depth: int = typer.Option(1, "--depth", "-d", help="Tree depth (1 = direct children only)."),
):
    """Print a hierarchical tree view rooted at the given object."""
    ws = _ws_or_die(workspace)
    client = ToscaCommanderClient()
    _output_json(_safe_call(f"tree {object_id}", client.object_tree, ws, object_id, depth=depth))


@objects_app.command("associations")
def objects_associations(
    object_id: str = typer.Argument(..., help="UniqueId of the object."),
    name: Optional[str] = typer.Option(None, "--name", "-n",
                                       help="Specific association name (e.g. 'Subparts'). Omit for all."),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
):
    """List object associations (typed or all)."""
    ws = _ws_or_die(workspace)
    client = ToscaCommanderClient()
    _output_json(_safe_call(f"associations {object_id}", client.object_associations, ws, object_id, assoc_name=name))


# ---------------------------------------------------------------------------
# `meta` subcommands
# ---------------------------------------------------------------------------

@meta_app.command("list")
def meta_list_cmd(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
):
    """List all object types known to this workspace."""
    ws = _ws_or_die(workspace)
    client = ToscaCommanderClient()
    _output_json(_safe_call("meta list", client.meta_list, ws))


@meta_app.command("type")
def meta_type_cmd(
    type_name: str = typer.Argument(..., help="TCAPI type name (e.g. TestCase, Module, ExecutionList)."),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
):
    """Inspect a single object type — fields, associations, and exposed tasks."""
    ws = _ws_or_die(workspace)
    client = ToscaCommanderClient()
    _output_json(_safe_call(f"meta {type_name}", client.meta_for_type, ws, type_name))


# ---------------------------------------------------------------------------
# `search` (TQL) — primary discovery primitive
# ---------------------------------------------------------------------------

@search_app.command("tql")
def search_tql(
    tql: str = typer.Argument(..., help='TQL query, e.g. =>Subparts:TestCase[Status=="Planned"]'),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
    root: Optional[str] = typer.Option(None, "--root", "-r",
                                       help="UniqueId of the search root. Defaults to the project root."),
):
    """Run a TQL query starting from --root (default: project root)."""
    ws = _ws_or_die(workspace)
    client = ToscaCommanderClient()
    if not root:
        proj = _safe_call("resolve project root", client.workspace_project_root, ws)
        # The project-root response usually exposes its UniqueId as 'UniqueId' or similar.
        root = proj.get("UniqueId") or proj.get("id") or proj.get("Id")
        if not root:
            _exit_err(
                "Could not resolve project root UniqueId from response. "
                "Pass --root explicitly with a folder/object id."
            )
    _output_json(_safe_call("tql search", client.tql_search, ws, root, tql))


# ---------------------------------------------------------------------------
# `task` — execute object or workspace-level tasks
# ---------------------------------------------------------------------------

@task_app.command("object")
def task_object_cmd(
    object_id: str = typer.Argument(..., help="UniqueId of the target object."),
    task_name: str = typer.Argument(..., help="TCAPI task name (e.g. Run, CheckIn, EnableExecutionApproval)."),
    param: list[str] = typer.Option([], "--param", "-p",
                                    help="key=value parameter; repeat for multiple."),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
    method: str = typer.Option("post", "--method", help="HTTP method: post (default) or get."),
):
    """Execute a task on a specific object."""
    ws = _ws_or_die(workspace)
    if method.lower() not in ("get", "post"):
        _exit_err("--method must be 'get' or 'post'.")
    client = ToscaCommanderClient()
    params = _kv_to_dict(param) if param else None
    _output_json(_safe_call(
        f"task {object_id}/{task_name}",
        client.task_object, ws, object_id, task_name,
        params=params, post=method.lower() == "post",
    ))


@task_app.command("workspace")
def task_workspace_cmd(
    task_name: str = typer.Argument(..., help="Generic task: CheckInAll, UpdateAll, CompactWorkspace, RevertAll."),
    param: list[str] = typer.Option([], "--param", "-p", help="key=value; repeat for multiple."),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
):
    """Execute a workspace-level (generic) task — CheckInAll, UpdateAll, CompactWorkspace, RevertAll."""
    ws = _ws_or_die(workspace)
    client = ToscaCommanderClient()
    params = _kv_to_dict(param) if param else None
    _output_json(_safe_call(
        f"ws-task {task_name}",
        client.task_workspace, ws, task_name, params=params,
    ))


@task_app.command("run")
def task_run(
    exec_list_id: str = typer.Argument(..., help="UniqueId of the ExecutionList to run."),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
    wait: bool = typer.Option(False, "--wait",
                              help="Block until the run completes (polls the execution log)."),
    poll_interval: float = typer.Option(5.0, "--poll-interval",
                                        help="Seconds between polls when --wait is set."),
    timeout: float = typer.Option(1800.0, "--timeout",
                                  help="Maximum seconds to wait when --wait is set."),
):
    """Execute the `Run` task on an ExecutionList. Mirrors pressing F6 in Tosca Commander."""
    ws = _ws_or_die(workspace)
    client = ToscaCommanderClient()
    result = _safe_call(
        f"Run {exec_list_id}", client.task_object, ws, exec_list_id, "Run",
    )
    _output_json(result)
    if not wait:
        return
    # Poll the ExecutionList itself for state changes — depth=2 brings the log in.
    deadline = time.time() + timeout
    last_state: str | None = None
    while time.time() < deadline:
        time.sleep(poll_interval)
        try:
            obj = client.object_get(ws, exec_list_id, depth=1)
        except ToscaCommanderError as e:
            console.print(f"[yellow]poll error[/yellow] HTTP {e.status} – {e.body[:120]}")
            continue
        # State property location differs per Tosca version. ExecutionList carries
        # the rolled-up state under various keys; ExecutionLogEntry uses
        # ExecutionStatus. Probe all known names.
        props = obj.get("Properties") or {}
        state = (
            props.get("ActualLogState")
            or props.get("ExecutionStatus")
            or props.get("Status")
            or props.get("Result")
            or props.get("LastExecutionStatus")
        )
        if state and state != last_state:
            console.print(f"[cyan]state →[/cyan] {state}")
            last_state = state
        if state and str(state).lower() in {
            "passed", "failed", "skipped", "notexecuted",
            "completed", "completedwithfailure",
        }:
            console.print(f"[bold]Final state:[/bold] {state}")
            _output_json(obj)
            return
    _exit_err(f"--wait timed out after {timeout:.0f}s without a terminal state.")


# ---------------------------------------------------------------------------
# `files` — attached files (incl. screenshots from FileService per KB0021775)
# ---------------------------------------------------------------------------

@files_app.command("list")
def files_list(
    object_id: str = typer.Argument(..., help="UniqueId of the object that owns the files."),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
):
    """List files attached to an object (e.g. ExecutionLog → screenshots)."""
    ws = _ws_or_die(workspace)
    client = ToscaCommanderClient()
    _output_json(_safe_call(f"files list {object_id}", client.file_list, ws, object_id))


@files_app.command("get")
def files_get(
    object_id: str = typer.Argument(..., help="UniqueId of the object that owns the file."),
    file_id: str = typer.Argument(..., help="File id (from `files list`)."),
    save: Optional[Path] = typer.Option(None, "--save", "-o",
                                        help="Path to save the file. Omit to print metadata."),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
):
    """Download or inspect a single attached file."""
    ws = _ws_or_die(workspace)
    client = ToscaCommanderClient()
    out = _safe_call(f"files get {file_id}", client.file_get, ws, object_id, file_id, save_to=save)
    if isinstance(out, dict):
        _output_json(out)
    elif isinstance(out, bytes):
        sys.stdout.buffer.write(out)


@files_app.command("logs")
def files_logs(
    exec_log_id: str = typer.Argument(..., help="UniqueId of an ExecutionLog (or ExecutionLog folder)."),
    save_dir: Path = typer.Option(Path("./tosca-logs"), "--dir",
                                  help="Directory to save logs+screenshots."),
    extension: str = typer.Option("png", "--ext",
                                  help="File extension to filter on (e.g. png, txt). Use '*' for all."),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
):
    """Walk an ExecutionLog → AttachedExecutionLogFile (TQL) → download each file.

    Implements the KB0021775 pattern. Default filters by .png; use `--ext '*'` for everything.
    """
    ws = _ws_or_die(workspace)
    client = ToscaCommanderClient()
    save_dir.mkdir(parents=True, exist_ok=True)

    # The walk root may be either an ExecutionList, an ExecutionLogEntry, or any
    # ancestor folder — TQL =>SUBPARTS recurses through the whole subtree, so a
    # single query covers all three cases.
    if extension == "*":
        tql = "=>SUBPARTS:AttachedExecutionLogFile"
    else:
        tql = f'=>SUBPARTS:AttachedExecutionLogFile[FileExtension="{extension}"]'

    found = _safe_call("tql ExecutionLog files", client.tql_search, ws, exec_log_id, tql)
    items = found if isinstance(found, list) else (found.get("items") or found.get("Items") or [])
    if not items:
        console.print(f"[yellow]No matching files under ExecutionLog {exec_log_id} (filter: {extension}).[/yellow]")
        return

    saved: list[dict] = []
    for it in items:
        # Robust id extraction across possible response shapes.
        oid = (it.get("UniqueId") or it.get("id") or it.get("Id")
               or (it.get("ref") or {}).get("UniqueId"))
        name = (it.get("Name") or "").strip() or oid
        if not oid:
            continue
        try:
            files = client.file_list(ws, oid)
        except ToscaCommanderError as e:
            console.print(f"[yellow]skip {oid}: list failed HTTP {e.status}[/yellow]")
            continue
        flist = files if isinstance(files, list) else (files.get("Files") or files.get("items") or [])
        for f in flist:
            fid = f.get("FileId") or f.get("Id") or f.get("id")
            ext = f.get("FileExtension") or extension
            if not fid:
                continue
            target = save_dir / f"{name}.{ext}".replace("/", "_").replace("\\", "_")
            client.file_get(ws, oid, fid, save_to=target)
            saved.append({"object": oid, "file": str(target)})

    _output_json({"saved": saved, "count": len(saved), "dir": str(save_dir)})


# ---------------------------------------------------------------------------
# `approvals` — pre-execution approval workflow
# ---------------------------------------------------------------------------

@approvals_app.command("enable")
def approvals_enable(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
):
    """Enable pre-execution approval at the project root."""
    ws = _ws_or_die(workspace)
    client = ToscaCommanderClient()
    proj = _safe_call("project root", client.workspace_project_root, ws)
    root = proj.get("UniqueId") or proj.get("id")
    if not root:
        _exit_err("Could not resolve project root UniqueId.")
    out = _safe_call("EnableExecutionApproval", client.task_object, ws, root, "EnableExecutionApproval")
    _output_json(out)
    console.print("[dim]Reminder: every approval workflow task must be followed by `task workspace CheckInAll`.[/dim]")


@approvals_app.command("disable")
def approvals_disable(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
):
    """Disable pre-execution approval at the project root."""
    ws = _ws_or_die(workspace)
    client = ToscaCommanderClient()
    proj = _safe_call("project root", client.workspace_project_root, ws)
    root = proj.get("UniqueId") or proj.get("id")
    if not root:
        _exit_err("Could not resolve project root UniqueId.")
    out = _safe_call("DisableExecutionApproval", client.task_object, ws, root, "DisableExecutionApproval")
    _output_json(out)


@approvals_app.command("request")
def approvals_request(
    object_id: str = typer.Argument(..., help="UniqueId of the TestCase to request approval for."),
    json_file: Optional[Path] = typer.Option(None, "--json-file", "-f",
                                             help="Optional JSON body for the request."),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
):
    """Request pre-execution approval for a TestCase."""
    ws = _ws_or_die(workspace)
    body = json.loads(json_file.read_text()) if json_file and json_file.exists() else None
    client = ToscaCommanderClient()
    _output_json(_safe_call(f"approval/request {object_id}", client.approval_request, ws, object_id, body))
    console.print("[dim]Reminder: follow with `task workspace CheckInAll` to persist the workflow change.[/dim]")


@approvals_app.command("give")
def approvals_give(
    object_id: str = typer.Argument(..., help="UniqueId of the TestCase to approve."),
    json_file: Optional[Path] = typer.Option(None, "--json-file", "-f",
                                             help="Optional JSON body (response payload)."),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w",
                                            envvar="TOSCA_COMMANDER_WORKSPACE"),
):
    """Give pre-execution approval to a TestCase."""
    ws = _ws_or_die(workspace)
    body = json.loads(json_file.read_text()) if json_file and json_file.exists() else None
    client = ToscaCommanderClient()
    _output_json(_safe_call(f"approval/give {object_id}", client.approval_give, ws, object_id, body))
    console.print("[dim]Reminder: follow with `task workspace CheckInAll` to persist the workflow change.[/dim]")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
