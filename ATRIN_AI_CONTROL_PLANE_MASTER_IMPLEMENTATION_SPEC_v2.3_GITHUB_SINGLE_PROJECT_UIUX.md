# ATRIN AI CONTROL PLANE
# MASTER IMPLEMENTATION SPECIFICATION v2.3

## 0. STATUS

This document is the authoritative implementation specification for the Atrin AI Control Plane.
It is intended to be given directly to an AI coding agent / coding AI that has access to the real Atrin repository.

This is NOT a demo specification.
This is NOT a proposal for a Qwen bridge.
This is NOT a requirement to build a vendor-specific AI wrapper.

The implementation target is a production-oriented, Windows-installable, local-first desktop product with a vendor-neutral AI orchestration core.

### 0.2 AUTHORITATIVE IMPLEMENTATION REPOSITORY — P0

The ONLY repository/project target for this specification is:

`https://github.com/mahmadifarpooyagroup-png/Execute-and-provide-output`

This repository is the single source location for implementation work under this specification.

Mandatory rules:

- Work ONLY inside the repository above.
- Do NOT switch to, clone from, copy from, merge with, or implement in another project/repository unless the user explicitly changes the repository target.
- Do NOT assume that another Atrin repository exists.
- Do NOT assume that any previous conversation, previous implementation, previous branch, previous project, or previous codebase exists.
- Treat the repository above as the complete and authoritative implementation workspace for THIS project.
- Start by inspecting the actual contents, branch, status, files, configuration, README, commits, and available code in this repository.
- If the repository is empty or contains only a minimal bootstrap, build the project from this specification inside this repository.
- Do NOT invent a second repository, demo repository, temporary replacement project, parallel implementation, or unrelated workspace.
- All source code, configuration, documentation, tests, scripts, and release artifacts produced for this project must belong to this repository unless a generated external artifact is technically unavoidable.
- When Git operations are required, use this repository as the target repository.
- If a requested implementation appears to require another repository, STOP and report the issue instead of silently changing the project target.
- The repository URL above is a project boundary, not merely an example link.

### 0.1 Changelog (v2.1 -> v2.2)

This revision preserves the full architectural specification while correcting
the implementation target so that any AI coding agent starts from the single
repository explicitly designated below, without assuming prior project history,
without switching to another project, and without inventing a replacement
repository:

- The implementation target is now explicitly bound to the single GitHub repository:
  `https://github.com/mahmadifarpooyagroup-png/Execute-and-provide-output`
- The AI coder must start from the actual repository contents and must not assume
  previous project history, another repository, a predefined stack, or an existing
  Atrin codebase.
- The previous assumptions about an existing `.NET/React` structure and existing
  Qwen code are now conditional on actual repository evidence.
- Qwen and other providers remain optional adapters, not assumed starting
  dependencies.
- The specification remains the architectural source of truth for the same
  production-oriented Atrin product and all existing security, recovery,
  authentication, workflow, verification, packaging, and acceptance requirements
  remain in force.

---

# 1. EXECUTIVE PRODUCT DEFINITION

Atrin is a **Windows Desktop AI Control Plane and Universal AI Orchestration Platform**.

Its purpose is to let a human configure, connect, authenticate, orchestrate, supervise, verify, recover, and replace heterogeneous AI systems and execution tools without modifying the orchestration core.

The system must be able to work with:

- Web AI providers
- Desktop AI applications
- API providers
- CLI coding agents
- Local AI models
- Remote AI agents
- MCP servers/tools
- A2A agents
- ACP-compatible coding agents
- Windows applications
- WSL/Linux environments
- PowerShell/CMD/Bash
- Git/GitHub
- Browser automation
- Filesystems and other tools/services

The user must be able to add a provider primarily through configuration rather than source-code changes.

The user must be able to change the provider used for a role without rewriting the orchestrator.

The system must preserve authenticated sessions where technically possible and must not ask the user to re-enter credentials on every workflow cycle.

---

# 2. NON-NEGOTIABLE ARCHITECTURAL PRINCIPLES

## 2.1 Vendor neutrality

Never hard-code a vendor, model family, AI website, desktop AI application, coding agent, endpoint, selector set, or CLI tool into the orchestrator core.

Examples of vendors/agents that MUST NOT be architectural dependencies of Core:

- Qwen
- Claude
- Gemini
- OpenAI / ChatGPT
- Codex
- Qwen Code
- Claude Code
- Gemini CLI
- OpenCode
- Goose
- Cline
- Cursor
- browser-use
- OmniRoute
- any future provider

All such systems are adapters/providers.

### Forbidden Core pattern

```text
if provider == "qwen": ...
if provider == "claude": ...
if provider == "gemini": ...
```

### Required pattern

```text
provider -> adapter -> generic contract
```

---

## 2.2 Configuration over code

Changing a provider endpoint, account, preferred model, profile, or routing policy must normally be a configuration operation, not a source-code change.

---

## 2.3 Workflow independence

Atrin Workflow state must remain independent of:

- provider implementation
- browser session implementation
- MCP session semantics
- ACP session semantics
- A2A task state
- desktop application lifecycle

External sessions may be referenced from workflow state, but must not become the authoritative workflow state.

---

## 2.4 Network failure is not authentication failure

Never equate:

- timeout
- DNS failure
- offline state
- connection reset
- temporary HTTP failure

with an authentication failure unless there is evidence that authentication itself became invalid.

---

## 2.5 Authentication failure is not workflow failure

A workflow must be able to enter a recoverable state such as:

```text
WAITING_FOR_AUTH
```

and resume from its last safe checkpoint after manual re-authentication.

---

## 2.6 Agent output is not evidence

An agent saying "done" or "tests passed" is not sufficient proof.

Verification must use actual execution evidence where applicable:

- exit code
- test output
- changed files
- diff
- browser state
- HTTP status
- process state
- artifact existence
- expected-state validation

---

# 3. TARGET USER EXPERIENCE

The final user experience should be:

```text
INSTALL ATRIN
    |
    v
OPEN ATRIN
    |
    v
FIRST-RUN SETUP
    |
    v
ADD AI / AGENT / TOOL
    |
    +--> Choose type: Web / Desktop / API / CLI / MCP / A2A / ACP / Local
    |
    v
MANUAL LOGIN IF REQUIRED
    |
    v
SAVE/RETAIN SESSION
    |
    v
RUN WORKFLOW
    |
    v
ATRIN ORCHESTRATES
    |
    +--> plan
    +--> select provider
    +--> execute
    +--> observe
    +--> verify
    +--> replan if necessary
    |
    +--> network loss -> pause/recover/resume
    +--> auth loss -> notify/manual login/resume
    +--> human action -> pause/notify/resume
    |
    v
HUMAN APPROVAL WHEN REQUIRED
    |
    v
COMPLETE / COMMIT / PUSH ACCORDING TO POLICY
```

The application should feel like one coherent product, not a collection of unrelated scripts.

---

# 4. HIGH-LEVEL ARCHITECTURE

```text
                         +----------------------+
                         |   ATRIN WINDOWS APP  |
                         | React + Desktop Host  |
                         +----------+-----------+
                                    |
                              Local IPC/API
                                    |
                    +---------------v----------------+
                    |       ATRIN CONTROL PLANE       |
                    |                                  |
                    | Provider Registry                |
                    | Account/Profile Registry        |
                    | Session Manager                  |
                    | Capability Registry              |
                    | Routing/Policy Engine            |
                    | Workflow Engine                  |
                    | Checkpoint Store                |
                    | Recovery Engine                  |
                    | Execution Bus                   |
                    | Memory                           |
                    | Audit                            |
                    +---------------+-----------------+
                                    |
                              Adapter Layer
                                    |
      +-------------+--------------+---------------+----------------+
      |             |              |               |                |
      v             v              v               v                v
    WEB          DESKTOP          API             CLI          PROTOCOLS
      |             |              |               |          MCP/A2A/ACP
      |             |              |               |
      v             v              v               v
  Playwright     UIA/CDP        HTTP/SDK        Process/stdio
      |             |              |               |
      +-------------+--------------+---------------+
                                    |
                                    v
                         EXECUTION / TOOL BUS
                                    |
                  +-----------------+------------------+
                  |                                    |
                  v                                    v
              WINDOWS                              WSL/LINUX
          PowerShell/CMD                       Bash/Python/Docker
          Files/Git/Processes                  Git/Dev tools
                                    |
                                    v
                            VERIFY / AUDIT
                                    |
                                    v
                              HUMAN GATE
```

---

# 5. PRODUCT BOUNDARIES

Separate these concepts explicitly:

```text
ROLE
PROVIDER
PROVIDER PROFILE
ACCOUNT IDENTITY
ADAPTER
TRANSPORT
PROTOCOL
SESSION
WORKFLOW
TASK
CHECKPOINT
EXECUTION
TOOL
PERMISSION
POLICY
```

Do not collapse them into one generic "AI connection" object.

---

# 6. ROLE MODEL

Roles are logical purposes, not vendors.

Minimum roles:

- brain
- planner
- coding
- research
- browser_agent
- verifier
- reviewer
- execution_agent
- general_agent

A provider may expose multiple roles.

Example:

```text
Provider: Example AI
Roles:
  brain
  research
```

---

# 7. PROVIDER MODEL

A Provider describes a service/application/agent that Atrin can connect to.

Example:

```yaml
provider:
  id: provider-001
  name: My Coding AI
  role: coding
  connection_kind: web
  transport: browser
  endpoint: https://example.com
  adapter: generic-web
  enabled: true
  priority: 10
```

Provider fields should include at minimum:

- id
- name
- description
- roles
- connection_kind
- transport
- endpoint/url/path/command as applicable
- adapter_id
- protocol(s)
- capability declarations
- authentication policy
- account/profile references
- enabled state
- priority
- fallback policy
- trust level
- permissions policy
- version
- metadata
- health status
- timestamps

---

# 8. PROVIDER PROFILE / ACCOUNT MODEL

Do not assume one provider equals one account.

Required logical relationship:

```text
Provider
   |
   +-- Profile A
   |      |
   |      +-- Account A
   |      +-- Session A
   |      +-- Browser/App Profile A
   |
   +-- Profile B
          |
          +-- Account B
          +-- Session B
          +-- Browser/App Profile B
```

This enables one AI service to be used through multiple user accounts without mixing sessions.

---

# 9. CONNECTION KINDS

Minimum supported kinds:

```text
WEB
DESKTOP
API
CLI
LOCAL
REMOTE
MCP
A2A
ACP
```

The model must remain extensible.

---

# 10. ADAPTER MODEL

Core interfaces should be technology-neutral.

Conceptual contracts:

```text
IProviderAdapter
IBrainProvider
IAgentProvider
IExecutionProvider
IToolProvider
ISessionProvider
IAuthenticationProvider
IBrowserProvider
IDesktopProvider
IVerifier
IMemoryProvider
```

Possible implementations:

```text
GenericWebAdapter
QwenWebAdapter
ClaudeWebAdapter
GeminiWebAdapter
GenericDesktopAdapter
NativeWindowsDesktopAdapter
ElectronDesktopAdapter
CliAdapter
ApiAdapter
McpAdapter
A2AAdapter
AcpAdapter
```

Only adapters may contain provider-specific behavior.

---

# 11. WEB PROVIDER ARCHITECTURE

Do NOT make the assumption that all Web AIs have the same DOM, selectors, response format, or login mechanism.

The Web stack must be split into at least:

```text
Browser Engine
      |
      v
Persistent Web Session Adapter
      |
      v
Provider Interaction Strategy
      |
      +-- login detection
      +-- composer detection
      +-- send action
      +-- streaming/result extraction
      +-- model selection
      +-- error detection
      +-- provider-specific recovery
```

### Generic browser layer

Responsibilities:

- launch browser
- attach to browser
- manage contexts
- persistent profile
- cookies
- local storage
- IndexedDB
- navigation
- page lifecycle
- browser crash recovery
- evidence capture

### Provider interaction strategy

Responsibilities:

- locate composer
- enter text
- submit
- detect output
- detect provider error
- detect authentication challenge
- detect completion

Provider-specific selectors/DOM logic belong here, not in Core.

---

# 12. PERSISTENT AUTHENTICATION — P0 REQUIREMENT

This is one of the most important requirements of the system.

## First use

```text
Add provider
   |
   v
Select Web
   |
   v
Enter URL
   |
   v
Create/select dedicated profile
   |
   v
Open provider
   |
   v
USER MANUALLY LOGS IN
   |
   v
Atrin verifies authentication
   |
   v
Session becomes ACTIVE
```

## Later executions

```text
Load same provider profile
   |
   v
Load persistent authenticated state
   |
   v
Use existing session
```

### Absolute rule

Atrin must NOT ask the user for username/password again on each:

- workflow
- loop
- task
- iteration
- retry
- provider call

unless the provider actually requires re-authentication.

Atrin should not automate password entry by default.

---

# 13. AUTHENTICATION STATE

Minimum states:

```text
UNKNOWN
NOT_AUTHENTICATED
LOGIN_REQUIRED
AUTHENTICATING
AUTHENTICATED
ACTIVE
EXPIRED
AUTH_REJECTED
AUTH_ERROR
```

Separate operational waiting states:

```text
WAITING_FOR_AUTH
WAITING_FOR_HUMAN_INTERACTION
```

## 13.1 Mandatory state transition table

The states above are not a free-form list. The implementation must encode an
explicit `(current_state, event) -> new_state` table so no transition is left
to adapter-specific guessing. Minimum required transitions:

| Current state | Event | New state |
|---|---|---|
| UNKNOWN | provider_registered | NOT_AUTHENTICATED |
| NOT_AUTHENTICATED | login_flow_started | LOGIN_REQUIRED |
| LOGIN_REQUIRED | user_completes_login | AUTHENTICATING |
| AUTHENTICATING | adapter_confirms_login (positive evidence) | AUTHENTICATED |
| AUTHENTICATING | confirmation_timeout | LOGIN_REQUIRED |
| AUTHENTICATED | first_action_dispatched | ACTIVE |
| ACTIVE | action_succeeds | ACTIVE |
| ACTIVE | idle_timeout_elapsed | AUTHENTICATED |
| ACTIVE | adapter_detects_logout_marker (positive evidence) | EXPIRED |
| EXPIRED | — | LOGIN_REQUIRED (automatic) |
| ACTIVE / any | transport_error with NO auth evidence | NETWORK_UNAVAILABLE (never EXPIRED) |
| NETWORK_UNAVAILABLE | connectivity_restored + session_probe_ok | ACTIVE |
| NETWORK_UNAVAILABLE | connectivity_restored + session_probe_fails_with_auth_evidence | EXPIRED -> LOGIN_REQUIRED |
| any | provider_rejects_credentials | AUTH_REJECTED |
| any | unrecoverable_adapter_auth_error | AUTH_ERROR |

### Evidence rule (binding, implements principle 2.4)

A transition into `EXPIRED`, `AUTH_REQUIRED`, `AUTH_REJECTED`, or `AUTH_ERROR`
requires **positive evidence** of an invalid auth state: an explicit
login-page marker, an HTTP 401/403 from the provider, or an adapter-specific
"logged out" signal. A timeout, a dropped connection, or the mere absence of a
response is never sufficient evidence by itself — those route to
`NETWORK_UNAVAILABLE` / `PROVIDER_UNAVAILABLE` instead. Each adapter must
declare, in its own implementation, exactly which signals it treats as auth
evidence versus transport evidence; the Core enforces the state machine but
does not infer evidence types on the adapter's behalf.

---

# 14. MANUAL RE-AUTHENTICATION FLOW

When an existing session expires:

```text
ACTIVE
   |
   v
AUTH_REQUIRED
   |
   v
PAUSE WORKFLOW
   |
   v
PERSIST CHECKPOINT
   |
   v
NOTIFY USER
   |
   v
OPEN SAME PROFILE
   |
   v
USER MANUALLY LOGS IN
   |
   v
VERIFY AUTH
   |
   +---- FAIL ----> WAITING_FOR_AUTH
   |
   +---- PASS ----> ACTIVE
                         |
                         v
                    RESUME EXACT CHECKPOINT
```

Never restart the workflow from Task 1 unless explicitly required by policy or external-state verification.

---

# 15. HUMAN INTERACTION RECOVERY

Authentication is not the only situation requiring a human.

Support a generic state:

```text
WAITING_FOR_HUMAN_INTERACTION
```

Examples:

- MFA
- passkey
- phone approval
- manual confirmation
- unavoidable CAPTCHA/anti-bot challenge
- desktop application dialog
- security confirmation

Atrin must pause and notify the user rather than attempting to bypass such controls.

After the user completes the interaction, Atrin resumes from the checkpoint.

---

# 16. NETWORK RECOVERY

Network state must be modeled independently:

```text
NETWORK_AVAILABLE
NETWORK_UNAVAILABLE
NETWORK_RECOVERING
```

Flow:

```text
EXECUTING
   |
   v
NETWORK_UNAVAILABLE
   |
   v
PAUSE
   |
   v
WAIT / BACKOFF / HEALTH CHECK
   |
   v
NETWORK_AVAILABLE
   |
   v
RESUME
```

Do not request Login merely because network connectivity was lost.

If the provider simultaneously invalidates authentication, emit the correct authentication state based on actual evidence.

---

# 17. BROWSER PROFILE MANAGEMENT

Each Web Provider Profile should have a dedicated persistent browser profile by default.

Example:

```text
%LOCALAPPDATA%/Atrin/BrowserProfiles/
    provider-001-profile-a/
    provider-001-profile-b/
    provider-002-profile-a/
```

Never put these profiles inside the source repository.

Never commit them to Git.

Treat them as sensitive credential-equivalent data.

---

# 18. EXISTING BROWSER SUPPORT

Support optional modes:

```text
MANAGED_NEW_BROWSER
PERSISTENT_BROWSER
EXISTING_BROWSER
CDP_ATTACH
```

Existing logged-in browser sessions may be attached where technically supported.

An existing personal browser profile should not be assumed safe for arbitrary automation; prefer dedicated automation profiles.

## 18.1 CDP_ATTACH scope restriction (mandatory)

`CDP_ATTACH` is an elevated-trust mode: the underlying protocol technically
grants control over every open tab in the attached browser, not just the
target provider tab. This mode is therefore bound by explicit rules, not just
a warning:

- `CDP_ATTACH` requires a separate, explicit opt-in permission per provider profile — it must never be the implicit default just because a provider is Web-typed.
- Atrin's adapter logic must restrict itself to the specific target page/tab it opened or was explicitly pointed at. It must not enumerate, read, or act on other open tabs even though the CDP connection would technically allow it.
- Every `CDP_ATTACH` session start is a dedicated audit event (see section 42) distinct from `MANAGED_NEW_BROWSER` / `PERSISTENT_BROWSER` session starts, so this elevated mode is always independently traceable.

---

# 19. SESSION MODEL

A Session is a runtime authentication/connection instance.

Minimum attributes:

```text
session_id
provider_profile_id
account_id
transport
state
created_at
last_used_at
expires_at if known
lock_owner
health
metadata
```

Session must be independent from Workflow.

A Workflow may reference a Session.

A Session can be recreated while preserving Workflow identity.

---

# 20. SESSION LEASE / LOCK

A persistent provider profile must not be concurrently manipulated by multiple active automation instances unless explicitly supported.

Required states:

```text
AVAILABLE
LOCKED
RECOVERING
EXPIRED
```

Lock metadata:

```text
session_id
profile_id
workflow_id
owner_id
acquired_at
lease_expiry
fencing_token
```

Release locks safely after completion/crash recovery.

## 20.1 Fencing token (mandatory — closes the crashed-holder race)

`lease_expiry` alone is not sufficient: a holder process that has crashed but
not fully terminated (e.g. a hung thread still mid-call) could still dispatch
a command to the browser/adapter transport *after* another process has
reclaimed the lock via expiry. To prevent this:

- `fencing_token` is a monotonically increasing integer, scoped per `profile_id`, incremented on every successful lock acquisition (initial or reclaim).
- Every action dispatched through the Web/Desktop adapter for a locked profile must carry the `fencing_token` under which the caller acquired the lock.
- The adapter transport layer rejects any call tagged with a `fencing_token` lower than the profile's current token, even if the call arrives from what was previously a legitimate holder.
- Reclaiming an expired lease (`now() > lease_expiry` and no explicit release) increments `fencing_token` before the new holder is allowed to dispatch any action.

This makes lock reclaim safe under Phase-1's single-machine SQLite model, and
the same token contract carries over unchanged if the lock store is later
replaced by a distributed backend (Redis/etcd), per the general
config-over-code and replaceable-boundary principles in this document.

---

# 21. DESKTOP AI ARCHITECTURE

Desktop AI is NOT Web AI.

The Desktop Adapter must support a layered fallback strategy.

Preferred order:

```text
1. Native Windows UI Automation
2. Application-specific supported API/integration
3. Electron/Chromium CDP where applicable
4. CLI integration where available
5. Keyboard/mouse fallback only when necessary
6. Human intervention
```

Do not build the entire Desktop Adapter around screen coordinates.

Use structured UI Automation elements, names, control types, patterns, windows, and events whenever available.

Microsoft UI Automation provides programmatic access to most Windows UI elements and supports automated testing/interaction; applications may expose different levels of automation support, so fallback behavior is required.

---

# 22. DESKTOP LIFECYCLE

Desktop Adapter contracts should cover:

```text
launch
attach
focus
inspect
interact
read_output
detect_auth
detect_error
detect_human_interaction
restart
recover
close
```

Provider-specific application handling must remain outside Core.

---

# 23. API PROVIDERS

API providers should use a generic contract supporting, where applicable:

- authentication
- request/response
- streaming
- model selection
- structured output
- tool calling
- rate-limit handling
- timeout handling
- retries
- health checks

Do not assume OpenAI-compatible APIs are the only API model.

---

# 24. CLI PROVIDERS

CLI adapter must support:

- process launch
- environment isolation
- stdin
- stdout
- stderr
- exit code
- timeout
- cancellation
- process tree cleanup
- structured output parsing
- log capture
- restart policy

Do not assume a specific CLI.

---

# 25. CAPABILITY MODEL

Capabilities must be data-driven.

Minimum examples:

```text
reasoning
planning
research
web_access
coding
filesystem
terminal
git
browser
vision
documents
structured_output
streaming
tool_calling
persistent_session
manual_auth
mcp
a2a
acp
```

Each capability should support at least:

```text
DECLARED
DETECTED
VERIFIED
```

Example:

```text
coding = DECLARED
terminal = DETECTED
git = VERIFIED
```

Routing should be able to require verified capabilities for sensitive tasks.

---

# 26. PROVIDER ROUTING

The Orchestrator selects providers based on:

- role
- required capabilities
- verified capabilities
- availability
- authentication state
- trust level
- permission policy
- health
- priority
- user preference
- fallback policy

Example:

```yaml
coding:
  primary: provider-a
  fallback:
    - provider-b
    - provider-c
```

Provider selection must never be hard-coded.

---

# 27. FAILOVER POLICY

Different failures require different behavior.

```text
NETWORK_ERROR
  -> bounded retry/backoff/fallback

RATE_LIMIT
  -> provider-specific backoff and possible fallback

TEMPORARY_PROVIDER_ERROR
  -> bounded retry

AUTH_REQUIRED
  -> human recovery

MFA/HUMAN_CHALLENGE
  -> human interaction state

INVALID_INPUT
  -> no blind retry

PERMISSION_DENIED
  -> policy/human gate
```

Authentication errors should not automatically trigger destructive failover.

## 27.1 Reconciliation-before-fallback protocol (mandatory)

Failover to a fallback provider must never be dispatched blindly after a
primary-provider failure that occurred mid-action, because the primary may
have already produced a side effect before failing. The required sequence is:

```text
Primary provider step fails
   |
   v
Call primary adapter's external-state verification
(same mechanism as section 35, against the PRIMARY, not the fallback)
   |
   +-- NOT_STARTED / FAILED --> safe to dispatch fallback provider
   |
   +-- CONFIRMED --> mark step complete, do not repeat on fallback,
   |                 continue workflow from next step
   |
   +-- IN_PROGRESS / AMBIGUOUS --> pause workflow in WAITING_FOR_PROVIDER,
                                    require human decision before any
                                    fallback dispatch
```

The orchestrator must never guess when a partial side effect might already be
on the primary provider — ambiguity routes to a human, not to a retry.

## 27.2 Capability equivalence for fallback (mandatory)

Two providers are only valid fallbacks for each other for a given role if
they share the same declared `capability_profile_id` in the Provider Registry
(section 25). Equivalence is an explicit configuration decision made by
whoever registers the provider — it is never inferred by the router from
overlapping capability tags alone, since two "coding" providers may still
differ in side-effect semantics, output format, or tool behavior.

---

# 28. TRUST MODEL

Provider Profiles should have a trust level:

```text
UNTRUSTED
USER_APPROVED
TRUSTED
DISABLED
```

Default privileges should follow least privilege.

Third-party adapters should not automatically receive high-level execution permissions.

---

# 29. PERMISSION MODEL

Preserve the existing permission levels:

```text
0 READ_ONLY
1 EXECUTE_SAFE
2 WRITE
3 GIT_COMMIT
4 GIT_PUSH
```

Authentication must never silently grant any execution permission.

Permissions are enforced by the Execution/Policy layer, not by prompts alone.

---

# 30. DRY RUN / PREVIEW

Support a dry-run/preview mode where meaningful.

Before sensitive operations, display:

- intended actions
- affected files/resources
- provider
- permissions
- expected side effects

Potential sensitive actions:

- WRITE
- DELETE
- package install
- external side effect
- Git commit
- Git push

---

# 31. HUMAN GATE

Human-controlled states:

```text
APPROVE
REJECT
PAUSE
CANCEL
```

Human gate is distinct from authentication.

Example:

```text
VERIFY PASS
   |
   v
HUMAN GATE
   |
   +--> REJECT -> REPLAN
   |
   +--> APPROVE -> FINALIZE / GIT according to permissions
```

---

# 32. WORKFLOW ENGINE

Atrin owns its own workflow model.

Minimum states:

```text
IDLE
PLANNING
PLAN_READY
EXECUTING
OBSERVING
VERIFYING
REPLANNING
WAITING_FOR_AUTH
WAITING_FOR_NETWORK
WAITING_FOR_HUMAN_INTERACTION
WAITING_FOR_HUMAN_APPROVAL
WAITING_FOR_PROVIDER
RECOVERING
FINALIZING
REPORTING
COMPLETED
REJECTED
CANCELLED
FAILED
```

Core loop:

```text
USER GOAL
 -> PLAN
 -> TASKS
 -> SELECT PROVIDER
 -> EXECUTE
 -> OBSERVE
 -> VERIFY
 -> PASS/FAIL
 -> REPORT
 -> HUMAN GATE
 -> COMPLETE / REPLAN
```

---

# 33. DURABLE CHECKPOINTS

Persist checkpoints after meaningful state transitions and before/after significant side effects.

Minimum checkpoint fields:

```text
workflow_id
task_id
step_id
state
current_action
provider_id
provider_profile_id
session_id
adapter_id
provider_version
adapter_version
action_idempotency_key
last_result
evidence	error
timeouts/retry state
timestamp
checkpoint_version
```

Also persist:

- completed tasks
- pending tasks
- failed tasks
- plan version
- policy version
- routing decision

## 33.1 Checkpoint write granularity (mandatory)

"After meaningful state transitions and before/after significant side
effects" is made concrete as follows. A checkpoint MUST be written:

1. immediately before any side-effecting action is dispatched (state = action pending, `action_idempotency_key` already assigned),
2. immediately after that action's result is confirmed (state = action confirmed, `last_result` and `evidence` populated),
3. on every Workflow Engine state transition listed in section 32.

This bounds the "unprotected window" between two checkpoints to at most one
in-flight action, which is what makes the crash-recovery reconciliation in
section 68 actually safe rather than aspirational.

## 33.2 Atomicity (mandatory)

The checkpoint write and the corresponding idempotency-ledger update (section
35) must be committed as a single local database transaction — both succeed
or neither does. WAL mode alone does not guarantee this; the write path must
explicitly wrap both operations in one transaction boundary.

## 33.3 Checkpoint schema versioning

`checkpoint_version` (already a required field above) is not a display label
— it drives a migration path. A checkpoint-migration registry (pure functions
keyed by `(from_version, to_version)`) runs on read whenever a stored
checkpoint's version is older than the current schema. Migrations must be
additive and non-destructive: unknown/newer fields encountered on a rollback
of Atrin itself are preserved, not dropped, so downgrading the application
does not corrupt checkpoints written by a newer version.

---

# 34. EXACT RESUME

If a workflow is interrupted because of:

- authentication
- network outage
- browser crash
- desktop application crash
- orchestrator restart
- controlled shutdown
- temporary provider failure

the workflow must resume from the latest safe checkpoint.

Do not restart from the beginning by default.

---

# 35. IDEMPOTENCY / EXTERNAL STATE VERIFICATION

Every side-effecting action **must** have an idempotency key. This is a
mandatory requirement, not a best-effort one — "when possible" is not an
acceptable implementation, because section 34 (Exact Resume) and section 27.1
(reconciliation-before-fallback) both depend on it being always available.

If an action may have succeeded before a connection failure, do NOT blindly repeat it.

First verify external state.

Example:

```text
WRITE_FILE
   |
transport failure
   |
UNKNOWN whether write happened
   |
verify file state
   |
then continue/retry safely
```

## 35.1 Idempotency ledger

```text
idempotency_key      (primary key)
workflow_id
step_id
provider_id
status                (PENDING | CONFIRMED | FAILED)
external_ref          (provider-side id/receipt if any)
created_at
confirmed_at
expires_at             (default: created_at + 30 days, then purged by a background job)
```

## 35.2 Mandatory adapter contract

Every adapter (Web, Desktop, CLI, API, MCP, A2A, ACP) must implement:

```text
adapter.verify_action(idempotency_key) -> NOT_STARTED | IN_PROGRESS | CONFIRMED | FAILED
```

Where a provider offers no server-side way to look up a past action (e.g. a
CLI tool with no run history), the adapter must still satisfy this contract
by writing a locally-durable receipt to the idempotency ledger *before*
dispatching the action, so a crash mid-action can be reconciled from the
ledger on restart even without provider cooperation.

## 35.3 Resume protocol

Before retrying any step from a checkpoint, the orchestrator calls
`verify_action()` first:

```text
CONFIRMED       -> skip, advance to next step
FAILED / NOT_STARTED -> safe to retry
IN_PROGRESS     -> poll with backoff before deciding
```

---

# 36. MCP ARCHITECTURE

Use MCP as a **Tool/Resource interoperability layer**, not as the Atrin workflow engine.

```text
Agent/Provider
      |
      v
     MCP
      |
      v
Tools / Resources / Services
```

Target the current stable MCP specification available at implementation time.

At the time of this specification, MCP `2026-07-28` is the current released specification and its core is stateless at the protocol layer; Tasks are handled through the extensions framework rather than defining the Atrin workflow itself.

Atrin Workflow state must remain independent of MCP protocol-level state.

Support compatibility adapters where practical.

Do not make Atrin's durable workflow depend on MCP Tasks.

---

# 37. A2A ARCHITECTURE

Use A2A for Agent-to-Agent interoperability, especially remote/distributed agents.

A2A should be treated as an adapter/protocol boundary.

The current stable A2A release is 1.0.0.

Use Agent Cards / supported interfaces / capabilities for discovery where available.

Do not make A2A the internal workflow state model.

---

# 38. ACP ARCHITECTURE

Use ACP for compatible local coding-agent interoperability.

ACP sessions may be referenced by Atrin, but Atrin must own its own workflow checkpoints.

ACP `session/resume` may be used as an integration primitive, not as a substitute for Atrin's durable workflow state.

---

# 39. EXECUTION BUS

AI and agents request actions through an execution layer.

They do not directly bypass policy to manipulate the operating system.

Execution targets include:

```text
PowerShell
CMD
Bash
WSL
Python
Node
Git
Filesystem
Docker
Processes
```

Every action should expose:

```text
action_id
permission_required
arguments
execution_target
status
stdout
stderr
exit_code
duration
evidence
```

---

# 40. LOCAL SECURITY BOUNDARY

The local AI Runtime may have high privileges, so its control interface is a security boundary.

Do not expose privileged control services on `0.0.0.0` by default.

Prefer, in order where practical:

1. Windows named pipe / equivalent local IPC
2. loopback-only HTTP/WebSocket
3. authenticated local IPC/HTTP with per-start secret and origin/request validation

The runtime must reject unauthorized requests.

Do not rely on obscurity or an arbitrary localhost port as security.

---

# 41. MEMORY

Memory must be independent of any AI provider.

Store, as appropriate:

- user goal
- project context
- plan
- tasks
- decisions
- constraints
- success criteria
- execution history
- verification evidence
- recovery history
- important provider choices

A provider may receive context from Atrin Memory, but must not own the authoritative project memory.

---

# 42. AUDIT

Record auditable events such as:

- provider selection
- login event
- logout event
- authentication failure
- manual recovery
- workflow state transition
- tool execution
- permission decision
- human approval/rejection
- provider failover
- checkpoint creation
- resume
- Git operation

Do not log raw passwords, secret tokens, or sensitive browser state contents.

## 42.1 Tamper-evident structure (mandatory)

Because Atrin can execute code and perform Git push operations, the audit
trail is a forensic record and must be tamper-evident, not just append-only
by convention. Each audit row must include:

```text
seq             (monotonic, autoincrement)
timestamp
workflow_id
event_type
actor           (system | user:<id> | provider:<id>)
payload
prev_hash       (hash of the previous row)
entry_hash      = hash(prev_hash || payload || timestamp)
```

`entry_hash` chains into the next row's `prev_hash`, so any modification of a
past row breaks the chain. A periodic verification job walks the chain and
flags any break. This does not require an external ledger — a local
hash-chain over the existing SQLite table is sufficient for Phase 1.

## 42.2 Retention

Audit rows are retained at least 90 days locally by default (configurable),
then rolled into a compressed archive rather than deleted outright. Audit
data is never silently pruned without an explicit user action, since it is
the primary evidence trail for git-push-capable automation.

---

# 43. SECRETS

By default do NOT store raw provider passwords.

Prefer:

```text
User manual login
   |
   v
Provider authenticates
   |
   v
Persistent authenticated profile/session
```

If Atrin itself must store a secret, use OS-protected storage appropriate to
Windows and the deployment environment. Because WSL/Linux is a first-class
execution target (sections 1, 39), "appropriate to the deployment
environment" is made concrete as follows:

| Environment | Small-secret storage | Notes |
|---|---|---|
| Windows (primary host) | DPAPI (`CryptProtectData`), user-scoped | Do not assume DPAPI covers an entire browser profile directory — see below |
| WSL/Linux processes launched by Atrin | `libsecret` (Secret Service API) via a `keyring`-style library; if no Secret Service is available, fall back to file permission `0600` on the secret file and `0700` on its containing directory | Needed because Execution Bus targets (PowerShell/CMD/Bash/WSL) may run as separate processes that still need controlled secret access |
| macOS (if ever supported) | Keychain Services | Not required for the Windows-first Phase 1 target, listed for forward compatibility |

Treat browser profile/authentication state as sensitive secret-equivalent
material. OS-level file-encryption features (DPAPI included) must not be
assumed to automatically cover an entire browser profile directory — profile
directories are additionally protected by OS file permissions/ACLs
regardless of what disk-level encryption is present.

---

# 44. WINDOWS DESKTOP PRODUCT

The final deliverable must be a real installable Windows application with a complete user-friendly graphical management environment.

The Windows desktop application is a first-class product surface, not an optional wrapper. All normal administration and workflow supervision must be possible through its UI/UX.

It must NOT require the end user to manually install development tooling just to run Atrin.

Final product should support:

- installer
- uninstaller
- Start Menu entry
- desktop shortcut where selected
- first-run setup
- persistent app data
- migration/update-safe data paths
- logging
- crash recovery
- configuration persistence
- runtime health

Expected artifact shape:

```text
Atrin-Setup.exe
```

The exact installer technology may be selected after repository inspection.

---

# 44.1 MANDATORY USER-FRIENDLY UI/UX AND DESKTOP MANAGEMENT

The final product MUST include a real, polished, user-friendly graphical UI/UX for ordinary Windows users. The desktop application is not merely a technical shell around the Control Plane; it is the primary management interface for Atrin.

The user MUST be able to install, launch, configure, monitor, control, pause, resume, recover, and manage Atrin entirely from the Windows desktop application without needing to use a terminal for normal operation.

## Mandatory UI/UX requirements

- Modern, clean, responsive and professional desktop UI
- User-friendly navigation suitable for a non-programmer
- Clear visual hierarchy and understandable terminology
- Responsive layouts for common Windows desktop resolutions
- Light/Dark theme support where practical
- Clear status indicators for provider, network, authentication, workflow and runtime health
- Search and filtering for providers, workflows, tasks, logs and audit events
- Human-readable error messages with actionable recovery instructions
- Confirmation dialogs for destructive or security-sensitive operations
- Notifications for states requiring user attention
- Accessible controls, keyboard navigation and sensible focus behavior
- Loading, empty, success, warning and error states for all major screens
- No dependence on command-line knowledge for normal user workflows

## Desktop management capabilities

From the Windows desktop UI, the user MUST be able to:

1. Start and stop the Atrin runtime.
2. View runtime health and process status.
3. Add, edit, disable and remove AI providers.
4. Configure provider type, endpoint, account/profile, adapter, capabilities, priority and fallback policy.
5. Open a provider and perform manual login when required.
6. View authentication/session state without exposing passwords, cookies or tokens.
7. Create, start, pause, resume, retry and cancel workflows.
8. See the currently executing task, step, provider, checkpoint and recovery state.
9. Approve or reject actions that require human authorization.
10. See clear states such as LOGIN REQUIRED, NETWORK UNAVAILABLE, HUMAN ACTION REQUIRED, APPROVAL REQUIRED, PROVIDER UNAVAILABLE, WORKFLOW PAUSED and WORKFLOW RESUMED.
11. Inspect execution evidence, logs and audit history.
12. Run connection and health tests.
13. Manage application settings, data locations, permissions and backups.
14. View update status and perform supported application updates.
15. Recover from interrupted workflows through the UI.

## Required primary screens

At minimum, the desktop application should provide:

- Dashboard
- Providers
- Accounts / Profiles
- Sessions / Authentication
- Workflows
- Tasks / Runs
- Execution / Live Monitor
- Recovery Center
- Tools / Execution Bus
- MCP / A2A / ACP connections
- Logs
- Audit
- Settings
- Help / Diagnostics

The exact information architecture may be refined after repository inspection, but the final application MUST remain easy to understand and operate for a normal Windows user.

## First-run user experience

After installation, the application should open into a guided first-run experience rather than presenting a developer-oriented interface. The wizard should help the user verify the runtime, configure initial settings, add the first provider, authenticate if necessary, test the connection, and finish with a usable dashboard.

The application MUST create a normal Windows Start Menu entry and, when selected by the user, a desktop shortcut. It MUST launch as a desktop application and provide a persistent graphical management environment.

## UX safety rule

Never hide important system states behind technical logs. Technical diagnostics may be available through an advanced/diagnostics view, but normal users must see concise explanations and clear next actions.

---

# 45. DESKTOP SHELL RECOMMENDATION

Evaluate the available desktop shells against the existing Atrin stack.

Preferred candidate for the current architecture:

```text
React + TypeScript UI
        |
        v
Tauri 2 Desktop Shell
        |
        +--> local Atrin runtime
        +--> native Windows integration
```

Tauri 2 is a preferred starting point because it integrates with WebView2 on Windows and has Windows installer support, including an offline WebView2 installer option.

However, before implementation, verify the current stable documentation and confirm that the selected shell best fits the actual repository.

Do not introduce Electron merely because it is familiar.

Do not change the existing .NET/React business platform architecture without evidence.

---

# 46. RUNTIME ARCHITECTURE

Current recommended split:

```text
ATRIN DESKTOP UI
  React + TypeScript
        |
        v
Desktop Host
        |
        v
Local AI Runtime / Control Plane
  Python where appropriate
        |
        +--> Provider Registry
        +--> Session Manager
        +--> Workflow Engine
        +--> Recovery
        +--> Browser Automation
        +--> Desktop Automation
        +--> Execution Bus
        +--> Protocol Adapters
        +--> Audit / Memory
```

Existing Atrin .NET/React business application remains where it already provides domain/business functionality.

The AI Control Plane should be a separable bounded component rather than contaminating business-domain code with AI-provider logic.

---

# 47. LOCAL DATA LAYOUT

Prefer Windows-standard user-data directories.

Conceptually:

```text
%LOCALAPPDATA%/Atrin/
    app/
    data/
        database/
        configuration/
        providers/
        accounts/
        sessions/
        browser-profiles/
        workflows/
        memory/
        audit/
        logs/
    cache/
    backups/
```

Do not store mutable runtime data under Program Files or the source repository.

---

# 48. LOCAL DATABASE

Phase 1 preferred durable local store:

```text
SQLite
WAL enabled
```

Keep repository abstractions replaceable so a future server/enterprise persistence layer can be introduced without rewriting domain logic.

Do not introduce a distributed database merely for theoretical scalability.

---

# 49. PHASE 1 SHOULD BE MODULAR MONOLITH / LOCAL-FIRST

Do not split the AI Control Plane into many microservices in Phase 1.

Prefer:

```text
one local control-plane runtime
+ modular internal boundaries
+ explicit interfaces
+ replaceable adapters
```

Future extraction into services should remain possible.

---

# 50. TARGET REPOSITORY — START FROM THE ACTUAL PROJECT, NOT FROM HISTORY

The implementation must begin by inspecting the actual target repository:

`https://github.com/mahmadifarpooyagroup-png/Execute-and-provide-output`

This is the ONLY repository for this project.

The AI coder must assume **zero prior implementation knowledge** unless that information is directly present in the current repository contents. Do not rely on previous conversations, previous AI agents, undocumented history, or assumptions about what the project "used to be".

Mandatory bootstrap sequence:

1. Clone/open the target repository if it is not already present locally.
2. Inspect the repository root.
3. Inspect the current branch and Git status.
4. Inspect the commit history that actually exists in this repository.
5. Inspect README and all project documentation that actually exists in this repository.
6. Inspect all source code that actually exists in this repository.
7. Inspect frontend/backend/runtime structure only if those directories actually exist.
8. Inspect tests, scripts, configuration, package manifests, solution/project files, and build files that actually exist.
9. Determine whether the repository is empty, minimal, partially implemented, or already contains a working implementation.
10. Produce an architecture-gap/bootstrap report based ONLY on evidence found in this repository and this specification.
11. Then implement incrementally inside this repository.

### Repository reality rule

Do NOT assume a predefined directory structure.

Do NOT assume that the repository already contains:

- `backend/`
- `frontend/`
- `.NET`
- `React`
- `Python`
- `Tauri`
- Clean Architecture
- DDD
- Modular Monolith
- an AI bridge
- an AI agent
- Qwen integration
- any specific provider
- any specific framework
- any specific database

Those technologies may be selected or retained only after inspection and architectural evaluation.

If the repository already contains useful implementation, preserve it when compatible with this specification. If it does not, create the required structure from this specification in the same repository.

### Single-project rule

There is no "old Atrin project", "new Atrin project", "replacement project", "demo project", "bridge project", or "another repository" in the scope of this task.

There is exactly one implementation target:

`mahmadifarpooyagroup-png/Execute-and-provide-output`

All implementation decisions must remain inside that boundary.

---

# 51. PROVIDER-SPECIFIC CODE RULE

The project must be vendor-neutral at the Core level.

Do NOT assume that Qwen, Claude, Gemini, OpenAI, or any other provider already exists in the repository.

If inspection of the target repository reveals provider-specific code, do not automatically delete it. First determine whether it is useful and whether it can be isolated behind the generic adapter architecture.

If the repository contains Qwen-specific code, for example, it may be refactored into:

```text
GenericWebAdapter
      |
      +--> QwenWebAdapter
```

Likewise:

```text
GenericAgentContract
      |
      +--> Qwen Agent Adapter
```

But this is conditional on actual repository evidence. Qwen is NOT a required implementation dependency and is NOT the project identity.

Provider-specific implementations must remain behind adapter boundaries.

The Core must remain vendor-neutral whether the first provider implemented is Qwen, another provider, a local model, a desktop application, a CLI agent, an API, or a provider that did not exist when this specification was written.

---

# 52. MIGRATION RULE

Refactor incrementally.

For every refactor or migration that is actually required by repository evidence:

1. preserve verified working behavior where compatible
2. introduce the generic contract
3. move provider-specific implementation behind the adapter boundary
4. add tests
5. verify the affected workflow behavior
6. remove only obsolete or conflicting hard-coded paths

Do not perform a migration merely because this specification mentions a provider.
Avoid big-bang rewrites.

---

# 53. PROVIDER CONFIG VERSIONING

Configuration must be versioned.

Store enough metadata to identify which Provider/Adapter configuration a workflow used.

Example:

```text
provider_id
provider_config_version
adapter_id
adapter_version
policy_version
```

Old workflows must remain traceable even after the provider configuration changes.

---

# 54. ROUTING DECISION TRACE

For each provider selection, optionally/appropriately record:

```text
required role
required capabilities
candidate providers
rejected candidates + reason
selected provider
routing policy
trust/permission decision
```

This is important for debugging why the system selected one AI rather than another.

---

# 55. HEALTH MODEL

Provider health should be independent from authentication state.

Examples:

```text
HEALTHY
DEGRADED
UNAVAILABLE
UNKNOWN
```

Do not use one boolean `online=true/false` to represent everything.

Authentication, network, health and process state are separate dimensions.

---

# 56. OBSERVABILITY

Every major operation should have a correlation identifier.

Suggested hierarchy:

```text
correlation_id
workflow_id
task_id
step_id
action_id
session_id
```

Use structured logs.

Never leak secrets into logs.

---

# 57. BROWSER EVIDENCE

For Web tasks, evidence may include:

- response text
- response completion marker
- HTTP status when meaningful
- page state
- screenshot when needed
- relevant DOM evidence
- provider error indicators

Do not use screenshots as the only verification method when structured state is available.

---

# 58. DESKTOP EVIDENCE

For Desktop tasks, evidence may include:

- process state
- window identity
- UI Automation element state
- application output
- file changes
- screenshots when necessary

---

# 59. HUMAN NOTIFICATIONS

The Desktop App must make waiting states visible.

At minimum:

```text
LOGIN REQUIRED
NETWORK UNAVAILABLE
HUMAN ACTION REQUIRED
APPROVAL REQUIRED
PROVIDER UNAVAILABLE
WORKFLOW PAUSED
WORKFLOW RESUMED
```

Notifications should link directly to the relevant action where practical.

---

# 60. FIRST-RUN SETUP

The first-run wizard should allow:

```text
Welcome
  -> security/data location
  -> runtime health check
  -> add first provider
  -> choose Web/Desktop/API/CLI/... 
  -> manual login if needed
  -> test connection
  -> save profile
  -> finish
```

No developer command line should be required for normal setup.

---

# 61. PROVIDER UI

Provider management UI must show at minimum:

```text
Name
Type
Role
Endpoint
Profile/Account
Adapter
Capabilities
Authentication status
Health
Trust
Priority
Fallback
Permissions
Last used
Last login
```

Actions:

```text
Open
Login
Logout
Test Connection
Edit
Disable
Delete
Reset Session
```

---

# 62. SESSION UI

Show:

```text
Provider
Account
Profile
Session status
Locked by
Last activity
Authentication state
Health
```

Do not display raw cookies/tokens/passwords.

---

# 63. WORKFLOW UI

Show:

```text
Workflow status
Current task
Current step
Provider in use
Session state
Checkpoint
Retries
Waiting reason
Actions required from user
Evidence
```

Buttons:

```text
Pause
Resume
Cancel
Retry
Open Provider
Login
Approve
Reject
```

---

# 64. INSTALLER / RUNTIME PACKAGING

The final Windows installation should be self-contained enough for ordinary users.

Do not require manual installation of:

- Python runtime
- Node runtime
- Rust toolchain
- .NET SDK
- Playwright developer tooling

unless the specific runtime truly cannot be packaged; in that case the Installer must handle prerequisite installation transparently and document it.

Development-only toolchains must not be assumed to exist on an end user's machine.

---

# 65. WEBVIEW2 / DESKTOP INSTALLATION

The chosen desktop shell must handle WebView2 correctly on supported Windows versions.

An offline-capable installer should be considered because the product is intended to be usable in imperfect connectivity environments.

Verify the current installer guidance at implementation time.

---

# 66. APPLICATION UPDATE SAFETY

Updates must preserve:

- provider registry
- provider profiles
- account metadata
- sessions/profiles where technically valid
- browser profiles
- workflows/checkpoints
- memory
- audit
- configuration

Use data migrations where required.

Never silently delete user state on update.

---

# 67. UNINSTALL SAFETY

Uninstall should distinguish:

```text
Remove Application Only
Remove Application + User Data
```

Never delete browser profiles or workflow data without an explicit user choice.

---

# 68. CRASH RECOVERY

On application/runtime restart:

```text
load configuration
load sessions
validate locks
load active workflows
load checkpoints
reconcile external state where necessary
resume only when safe
```

Do not blindly resume side-effecting operations.

---

# 69. CONCURRENCY

Phase 1 must be concurrency-safe for local usage.

At minimum:

- one profile lock per active automated browser session
- workflow ownership
- action idempotency
- database transaction safety

Do not build multi-machine distributed coordination in Phase 1 unless required by actual project scope.

---

# 70. TESTING STRATEGY

Testing must cover unit, integration and end-to-end behavior.

## Provider tests

- registration
- update
- disable
- delete
- capability validation
- routing
- fallback

## Authentication tests

- first manual login
- persistent session reuse
- multiple workflow loops without relogin
- auth expiration
- manual relogin
- exact workflow resume
- logout

## Network tests

- outage
- pause
- no false authentication prompt
- recovery
- resume

## Session tests

- profile isolation
- lock acquisition
- lock contention
- unlock after completion
- crash recovery

## Workflow tests

- checkpoint
- restart
- resume
- retry
- failure
- replan
- human approval
- human rejection

## Execution tests

- PowerShell
- CMD
- WSL
- Bash
- Python
- Git
- file operations

## Security tests

- no plaintext credentials
- no secret leakage in logs
- local API authentication
- permission enforcement
- unauthorized provider action blocked

## Packaging tests

- clean Windows install
- first-run setup
- application launch
- update
- uninstall
- data retention

---

# 71. MANDATORY END-TO-END AUTHENTICATION ACCEPTANCE TEST

This test is P0.

```text
1. Install Atrin on Windows.
2. Launch Atrin.
3. Add a Web AI provider by URL.
4. Select connection type = Web.
5. Create/select a dedicated provider profile.
6. Open the provider.
7. Manually log in.
8. Atrin verifies authentication.
9. Run at least 3 workflow iterations.
10. Confirm that no repeated login is requested.
11. Simulate network outage.
12. Confirm workflow pauses.
13. Confirm no login prompt appears solely because of network loss.
14. Restore network.
15. Confirm workflow resumes.
16. Invalidate/expire provider authentication.
17. Confirm workflow transitions to WAITING_FOR_AUTH.
18. Confirm visible user notification.
19. Click LOGIN NOW.
20. Re-login manually in the same provider profile.
21. Confirm authentication.
22. Confirm workflow resumes from the exact checkpoint.
23. Confirm no task/context is lost.
24. Confirm the same provider profile/account is used.
25. Confirm raw password was never written to logs/database.
26. Close Atrin.
27. Reopen Atrin.
28. Confirm persisted provider/session/workflow state is recoverable.
```

---

# 72. MANDATORY PROVIDER-SWAP ACCEPTANCE TEST

```text
Day 1:
Brain = Provider A
Coding = Provider B

Day 2:
Brain = Provider C
Coding = Provider A
```

No Core/orchestrator code change may be required.

---

# 73. MANDATORY WEB/DESKTOP DISTINCTION TEST

```text
Provider A -> Web
Provider B -> Desktop
```

Verify that each uses the correct adapter and lifecycle.

---

# 74. MANDATORY RECOVERY TEST

At least these interruptions must be testable:

```text
network loss
provider timeout
provider rate limit
browser crash
desktop app crash
auth expiration
orchestrator restart
```

Each must result in a defined state transition and recovery policy.

---

# 75. TECHNOLOGY SELECTION RULE

Before adding dependencies, evaluate:

- necessity
- stability
- license
- maintenance status
- security history
- Windows compatibility
- offline/local behavior
- vendor lock-in
- footprint
- ease of packaging
- testability

Use official documentation as the source of truth for current protocol/API versions.

---

# 76. CURRENT STANDARDS BASELINE

At implementation time, verify the current official specifications.

At the time this document was authored:

- MCP current released specification: `2026-07-28`
- A2A current released specification: `1.0.0`
- ACP session resume is stable
- Playwright supports reuse of authenticated browser state and persistent browser profiles
- Windows UI Automation provides programmatic interaction with Windows UI elements
- Tauri 2 uses WebView2 on Windows and provides Windows installer options

Do not blindly copy these version statements if the official specifications have advanced by the time implementation starts. Verify them from official sources first.

---

# 77. CURRENT OFFICIAL REFERENCE SOURCES

Use these as implementation-time references:

```text
MCP:
https://modelcontextprotocol.io/
https://blog.modelcontextprotocol.io/posts/2026-07-28/

A2A:
https://a2a-protocol.org/
https://a2a-protocol.org/latest/

ACP:
https://agentclientprotocol.com/

Playwright:
https://playwright.dev/docs/auth
https://playwright.dev/docs/api/class-browsertype

Windows UI Automation:
https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-uiautomationoverview

Tauri:
https://v2.tauri.app/
https://v2.tauri.app/distribute/windows-installer/
```

Verify current details before implementation rather than relying on this list as a frozen API guarantee.

---

# 78. IMPLEMENTATION PHASES

## Phase 0 — Target repository bootstrap and architecture audit

- inspect ONLY `https://github.com/mahmadifarpooyagroup-png/Execute-and-provide-output`
- inspect repository root
- inspect current branch/status
- inspect actual commit history
- inspect README/documentation
- inspect actual source tree
- inspect actual frontend/backend/runtime structure if present
- inspect tests
- inspect build/package/configuration files
- identify any actual provider-specific coupling found in the repository
- determine whether the repository is empty, minimal, partial, or implemented
- write an evidence-based architecture/bootstrap gap report

Do not assume another project exists.
Do not rewrite blindly.
If the repository is empty/minimal, implement the project from this specification directly in this repository.

## Phase 1 — Core contracts

- Provider model
- Provider Profile model
- Account model
- Capability model
- Adapter contracts
- Session contracts
- policy contracts

## Phase 2 — Secure local runtime

- local control-plane process
- secure IPC/loopback API
- authentication of local requests
- process lifecycle
- health endpoint

## Phase 3 — Session and authentication

- session registry
- profile registry
- account identity
- persistent browser profiles
- session lock
- authentication state machine
- manual login gate

## Phase 4 — Generic Web Adapter

- Playwright
- persistent profile
- existing-browser/CDP support where practical
- generic browser actions
- provider interaction strategy abstraction
- auth detection
- response extraction

## Phase 5 — Recovery

- WAITING_FOR_AUTH
- WAITING_FOR_NETWORK
- WAITING_FOR_HUMAN_INTERACTION
- notification
- manual recovery
- exact resume

## Phase 6 — Durable Workflow

- state machine
- SQLite persistence
- checkpoints
- idempotency
- resume
- retry/recovery

## Phase 7 — Execution Bus

- PowerShell
- CMD
- WSL/Bash
- Python
- Git
- filesystem
- process management

## Phase 8 — Protocol adapters

- MCP
- ACP
- A2A

## Phase 9 — Desktop adapter

- Windows UI Automation
- process/window management
- CDP where applicable
- fallback strategy

## Phase 10 — Provider adapter hardening

- inspect which provider-specific implementations actually exist in the target repository
- move any discovered provider-specific transport behind GenericWebAdapter/provider boundaries
- preserve verified useful behavior
- remove vendor assumptions from Core
- do not add a provider-specific adapter merely because a provider is named in this specification

## Phase 11 — Desktop UI

- provider management
- profiles/accounts
- sessions/login
- workflow monitoring
- recovery/notifications
- permissions
- audit

## Phase 12 — Windows packaging

- desktop shell
- installer
- runtime packaging
- update strategy
- clean-machine installation test

## Phase 13 — End-to-end verification

Run all mandatory acceptance scenarios.

---

# 79. DEVELOPMENT RULE: DO NOT OVER-ENGINEER

Do not introduce in Phase 1 merely for architectural fashion:

- distributed microservices
- Kubernetes
- Kafka
- Temporal
- cloud-only control plane
- managed secrets service
- multi-region deployment

Keep boundaries replaceable, but keep the local implementation practical.

---

# 80. DEVELOPMENT RULE: DO NOT UNDER-ENGINEER SECURITY

Do not simplify away:

- session isolation
- permission checks
- local API authentication
- secrets handling
- audit
- provider trust
- workflow checkpoints

The system can execute code and control applications, so the control plane itself is security-sensitive.

---

# 81. DEVELOPMENT RULE: RESPECT PROVIDER SECURITY CONTROLS

Do not attempt to bypass:

- CAPTCHA
- MFA
- passkeys
- anti-bot controls
- provider security confirmations

Use the `WAITING_FOR_HUMAN_INTERACTION` state.

---

# 82. DEVELOPMENT RULE: PROTECT USER DATA

Never export or commit:

- cookies
- browser auth state
- access tokens
- passwords
- private keys
- sensitive logs

Never include these in bug reports automatically.

---

# 83. IMPLEMENTATION REPORT FORMAT

After each meaningful implementation stage, report:

```text
PHASE
IMPLEMENTED
FILES CHANGED
DEPENDENCIES ADDED
TESTS RUN
VERIFICATION EVIDENCE
KNOWN RISKS
ARCHITECTURAL DEVIATIONS
NEXT STEP
```

Do not claim success without evidence.

---

# 84. ARCHITECTURAL DEVIATION RULE

If implementation requires violating any of these core rules:

- vendor neutrality
- persistent session reuse
- exact checkpoint resume
- security boundary
- workflow independence
- provider/adapter separation

stop that change, record the deviation, explain the technical reason, and choose the least invasive alternative.

---

# 85. DEFINITION OF DONE

The product is considered ready only when all are true:

## Core

```text
AI-agnostic
Provider Registry
Provider Profiles
Account Identity
Adapter architecture
Capability routing
```

## Authentication

```text
manual first login
persistent session
no repeated login loops
auth detection
manual re-login
exact workflow resume
human interaction state
```

## Reliability

```text
network recovery
provider recovery
browser recovery
desktop recovery
orchestrator restart recovery
checkpoints
idempotency
```

## Execution

```text
Windows
WSL/Linux
PowerShell
CMD
Bash
Python
Git
Filesystem
```

## Interoperability

```text
Web Adapter
Desktop Adapter
CLI Adapter
API Adapter
MCP Adapter
ACP Adapter
A2A Adapter
```

## Governance

```text
permissions
human gate
dry run
audit
verification
evidence
```

## Product delivery

```text
Windows Desktop App
Installer
Uninstaller
First-run setup
Persistent user data
Safe updates
Clean-machine test
```

---

# 86. THE MOST IMPORTANT USER REQUIREMENT

The following behavior is mandatory and must be preserved above all convenience features:

```text
USER ADDS PROVIDER ONCE
        |
        v
USER CHOOSES WEB / DESKTOP / API / CLI / OTHER
        |
        v
USER MANUALLY LOGS IN ON FIRST USE
        |
        v
ATRIN RETAINS THE VALID SESSION/PROFILE
        |
        v
ALL SUBSEQUENT LOOP CYCLES REUSE IT
        |
        v
NO REPEATED USERNAME/PASSWORD PROMPTS
        |
        v
SESSION EXPIRES ONLY WHEN PROVIDER REQUIRES IT
        |
        v
ATRIN PAUSES ONLY THE AFFECTED WORKFLOW
        |
        v
ATRIN NOTIFIES USER
        |
        v
USER MANUALLY LOGS IN AGAIN
        |
        v
ATRIN VERIFIES
        |
        v
ATRIN RESUMES FROM EXACT CHECKPOINT
```

This requirement is P0 and must not be weakened by implementation shortcuts.

---

# 87. FINAL ARCHITECTURAL STATEMENT

Atrin is not an AI model.

Atrin is not a Qwen bridge.

Atrin is not a Claude bridge.

Atrin is not a vendor-specific router.

Atrin is a **local-first, vendor-neutral Control Plane** that can connect interchangeable AI brains, coding agents, browsers, desktop applications, protocols, tools and execution environments while maintaining durable workflows, persistent user sessions, security boundaries, human control and verifiable recovery.

The Core must know **what a provider can do**, **how to invoke its abstract contract**, **what permission it has**, **what state it is in**, and **how to recover**.

The Core must NOT need to know whether the provider happens to be Qwen, Claude, Gemini, OpenAI, a future unknown AI, or a custom application.

The final product must be installable and usable by an ordinary Windows user, not only by a developer.

---

# 88. FINAL INSTRUCTION TO THE AI CODER

Treat this document as the architectural source of truth.

Before writing implementation code:

1. Open/clone ONLY the target repository:
   `https://github.com/mahmadifarpooyagroup-png/Execute-and-provide-output`
2. Inspect its actual contents, branch, status, commits, documentation, source tree, tests, and build state.
3. Assume no prior implementation unless it is present and verifiable in that repository.
4. Do not use another repository or project as the implementation target.
5. Verify current official documentation for technologies being implemented.
6. Produce an evidence-based architecture/bootstrap gap report.
7. Implement incrementally inside the same target repository.
8. Preserve verified working behavior where compatible with this specification.
9. Isolate provider-specific functionality behind adapters when such functionality actually exists.
10. Add tests for every new boundary.
11. Prove the mandatory login/session/recovery behavior with end-to-end evidence.
12. Build a real Windows installer.
13. Verify installation and recovery on a clean Windows environment.

Never create or use a separate demo/replacement project.
Never silently change the repository target.

Never hard-code a vendor into the Core.

Never ask the user to log in repeatedly when a valid persisted session exists.

Never restart a workflow from the beginning solely because authentication or network connectivity was temporarily interrupted.

Never store raw passwords without an explicit and justified requirement.

Never claim success without executable evidence.

The final goal is a real, maintainable, installable Atrin product implemented ONLY in:

`https://github.com/mahmadifarpooyagroup-png/Execute-and-provide-output`

This repository is the single project boundary for the entire implementation.
