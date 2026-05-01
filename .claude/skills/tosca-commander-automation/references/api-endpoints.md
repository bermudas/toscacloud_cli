# TCRS API Endpoints Reference

Base URL: `http(s)://<host>:<port>/rest/toscacommander`

Extracted from the TCRS help page (`/rest/toscacommander/help/operations/`).

---

## Global

| Method | Path | Operation | Notes |
|--------|------|-----------|-------|
| GET | `/` | `ShowVersionInfo` | Returns service version info. Good as a liveness probe in `config test`. |
| GET | `/GetWorkspaces` | `GetWorkspaces` | Lists all workspaces available on this TCRS instance. |

---

## Workspace lifecycle

| Method | Path | Operation | Notes |
|--------|------|-----------|-------|
| GET | `/{Workspace}` | `OpenWorkSpace` | Opens (connects to) a workspace. Required before any workspace-scoped call. |
| GET | `/{Workspace}/projectid` | `GetProjectId` | Returns the project/repository GUID for the workspace. |
| GET | `/{Workspace}/revision` | `GetRevisionInfo` | Returns current revision info (head revision, pending changes, etc.). |
| GET | `/{Workspace}/getSettingsFiles` | `GetSettingsFiles` | Lists workspace-level settings files. |
| POST | `/{Workspace}/getissues` | `GetIssues` | Returns validation issues for workspace objects. |

---

## Metadata / schema discovery

| Method | Path | Operation | Notes |
|--------|------|-----------|-------|
| GET | `/{Workspace}/metainfo` | `GetMetaInfo` | Lists all known TCRS object types (TestCase, Module, ExecutionList, …). |
| GET | `/{Workspace}/metainfo/{type}` | `GetTypeInfo` | Returns schema info for a specific object type. |
| GET | `/{Workspace}/metainfo/{type}/associations` | `GetAssociationsInfo` | Lists association names valid for `{type}` (e.g. `Owner`, `TestSteps`, `Subtypes`). |
| GET | `/{Workspace}/metainfo/{type}/attributes` | `GetAttributesInfo` | Lists attribute names and types valid for `{type}`. |

---

## Object CRUD

| Method | Path | Operation | Notes |
|--------|------|-----------|-------|
| GET | `/{Workspace}/object/{id}` | `ShowObject` | Fetch a single object by its 32-char UniqueId. Core read operation. |
| POST | `/{Workspace}/object` | `SetObject` | Create or update an object (upsert by UniqueId). Body is the object JSON. |
| GET | `/{Workspace}/object` | `GetObjectWithAbsolutePath` | Fetch an object by its absolute path string (e.g. `TestCases\Folder\MyTest`). |
| DELETE | `/{Workspace}/object/{id}` | `DeleteObject` | Hard-delete an object. Irreversible — always confirm before calling. |
| PUT | `/{Workspace}/object/{id}?name={FILENAME}` | `UploadFile` | Upload a file attachment to an object. `name` is the filename on disk. |
| PATCH | `/{Workspace}/object/{id}/setCustomProperty?name={NAME}&…` | `SetCustomProperty` | Set a single custom property value on an object. |

---

## Associations

| Method | Path | Operation | Notes |
|--------|------|-----------|-------|
| GET | `/{Workspace}/object/{id}/association` | `ShowAllAssociations` | Lists all association names for the given object. |
| GET | `/{Workspace}/object/{id}/association/{associationName}` | `ShowObjectAssociation` | Returns the raw association collection (UniqueIds). Use `Owner` to resolve parent. |
| GET | `/{Workspace}/object/{id}/resolvedassociation/{associationName}` | `ShowResolvedObjectAssociation` | Like above but returns full object bodies, not just IDs. Expensive on large collections. |

---

## Tasks (object-scoped)

Tasks are TCRS-side operations bound to a specific object (analogous to right-click menu actions in the Commander UI).

| Method | Path | Operation | Notes |
|--------|------|-----------|-------|
| GET | `/{Workspace}/object/{id}/task` | `GetTasks` | Lists all task names available for the object. |
| GET | `/{Workspace}/object/{id}/task/{taskName}` | `ExecuteTask` | Execute a named task with no body. |
| POST | `/{Workspace}/object/{id}/task/{taskName}` | `ExecuteTaskWithPOSTParameters` | Execute a named task with a JSON body (for tasks that accept parameters). |
| GET | `/{Workspace}/object/{id}/task/ExecuteNow` | `ExecuteTestEvent` | Runs a TestCase or ExecutionList immediately (equivalent to F6 in the UI). Use this for local smoke-test execution. |
| GET | `/{Workspace}/object/{id}/task/ExportAutomationObjects` | `ExportAutomationObjects` | Exports automation objects (TSU/XML) for the given object. |
| GET | `/{Workspace}/object/{id}/getDexConfigurations` | `GetDexConfigurations` | Lists DEX (Distributed Execution) configurations for the object. |

---

## Tasks (workspace-scoped / generic)

Workspace-level tasks apply to the whole workspace, not to a single object.

| Method | Path | Operation | Notes |
|--------|------|-----------|-------|
| GET | `/{Workspace}/task` | `GetGenericTasks` | Lists all generic workspace task names (`CheckInAll`, `UpdateAll`, `CompactWorkspace`, `RevertAll`, …). |
| GET | `/{Workspace}/task/{taskName}?checkincomment={COMMENT}` | `ExecuteGenericTask` | Execute a workspace task. `checkincomment` is used by check-in tasks. |
| POST | `/{Workspace}/task/{taskName}?checkincomment={COMMENT}` | `ExecuteGenericTaskWithPOSTParameters` | Same as GET variant but accepts a JSON body (for parameterized workspace tasks). |
| POST | `/{Workspace}/task/importaoresults` | `ImportAOResults` | Import Automation Object execution results into the workspace. |

---

## Execution log retrieval (KB0021775 pattern)

| Method | Path | Operation | Notes |
|--------|------|-----------|-------|
| GET | `/{Workspace}/object/{executionlistId}/testcaselogswithtestcases` | `GetTestCaseLogsWithTestCases` | Returns `ExecutionLog` entries with their linked TestCase objects for an ExecutionList run. Starting point for the KB0021775 log/screenshot walk. |

**Walk pattern:**
```
1. GetTestCaseLogsWithTestCases({executionlistId})
   → list of ExecutionLog objects, each with UniqueId

2. ShowObjectAssociation({logId}, "Subparts:AttachedExecutionLogFile")
   → list of file UniqueIds attached to each log entry

3. GetResource(source=FileService, uniqueid={fileId})
   → binary file content (logs.txt, screenshots, …)
```

---

## TQL search

| Method | Path | Operation | Notes |
|--------|------|-----------|-------|
| GET | `/{Workspace}/search?tql={QUERY}` | `Search` | Run a TQL query and return matching objects. Always URL-encode the `tql` parameter. |

**Common TQL patterns:**
```
# All TestCases in a folder
=>SUBPARTS:TestCase[Name=="MyTest"]

# Module by name
=>SUBPARTS:Module[Name=="LoginModule"]

# ExecutionLists
=>SUBPARTS:ExecutionList[Name contains "Smoke"]

# By UniqueId (for verification)
=>UNIQUEID["<32-char-id>"]
```

---

## Treeview navigation

Treeview endpoints return a lightweight tree representation (name + type + children links) without loading full object bodies — useful for folder browsing.

| Method | Path | Operation | Notes |
|--------|------|-----------|-------|
| GET | `/{Workspace}/treeview` | `GetTreeviewRootObject` | Returns the workspace root node. |
| GET | `/{Workspace}/treeview/{id}` | `GetTreeviewObject` | Returns a single treeview node by UniqueId. |
| GET | `/{Workspace}/treeview/{id}/subparts` | `GetTreeviewObjectSubparts` | Returns direct children of a treeview node. Prefer this over `ShowObject` for folder listing. |
| GET | `/{Workspace}/treeview/{id}/Associations/{association}` | `GetTreeviewObjectAsscociation` | Returns associated treeview nodes for a given association name. |

---

## Resource retrieval

| Method | Path | Operation | Notes |
|--------|------|-----------|-------|
| GET | `/{Workspace}/resource?source={SOURCETYPE}&uniqueid={ID}` | `GetResource` | Fetch a binary resource (log file, screenshot) by source type and UniqueId. `source=FileService` for KB0021775 attachments. |
| POST | `/{Workspace}/resource?source={SOURCETYPE}&uniqueid={ID}` | `GetResourceWithPOSTParameters` | Same as GET variant but accepts a JSON body for additional filter parameters. |

---

## Key constants

| Concept | Value |
|---------|-------|
| UniqueId format | 32 hex chars, uppercase, no dashes (e.g. `A1B2C3D4E5F6...`) |
| Default port (single-user) | `5004` |
| Default port (multi-user / server) | `1111` |
| Help page | `GET /rest/toscacommander` (returns this endpoint list as HTML) |
| Per-operation help | `GET /rest/toscacommander/help/operations/{OperationName}` |
