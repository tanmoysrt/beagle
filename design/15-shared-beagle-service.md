# 14 — Shared Beagle Service

## Goal

Build Beagle as a shared, revision-aware code-intelligence service for teams.

The service should:

- mirror private Git repositories;
- index commits once and reuse them across branches;
- reindex incrementally when new commits are pushed;
- support branches, tags, merge commits, and local working-tree overlays;
- download and analyze exact Python and JavaScript dependencies;
- identify the authenticated user talking through MCP;
- record who proposed, accepted, rejected, reviewed, or implemented a decision;
- index historical commit messages, authors, committers, timestamps, and trailers;
- preserve team-wide change summaries, decisions, and feedback;
- serve the same context to Claude Code, CI, local development, and future review workflows.

The primary identity of code is:

```text
repository + commit
```

A branch is only a mutable pointer to a commit.

---

## Key decisions

### Service first

Beagle should have:

```text
shared service
local MCP bridge
indexing workers
Git synchronization
```

The shared service owns:

```text
repository mirrors
revision indexes
dependency artifacts
decisions
feedback
historical context
access control
```

The local bridge owns:

```text
local repository discovery
current HEAD and branch
dirty working-tree detection
local patch generation
MCP communication with Claude Code
```

### Use JWT authentication

Use a simple server-minted JWT.

Do not build OAuth initially.

The JWT should contain:

```text
subject/user ID
organization ID
allowed repository scopes
permissions
issued-at time
expiry
token ID
```

Example claims:

```json
{
  "sub": "user_tanmoy",
  "org": "frappe",
  "repos": ["press", "frappe"],
  "permissions": [
    "source:read",
    "repo:sync",
    "decision:write",
    "feedback:write"
  ],
  "iat": 1781395200,
  "exp": 1781481600,
  "jti": "token_..."
}
```

The service must mint and sign the token.

The client must not mint its own trusted token.

Store the token in:

```text
OS keyring
credential helper
user-local secure config
```

Never store a personal token in the repository.

### Record authenticated user identity

Every MCP session and write operation must be tied to the authenticated JWT subject.

A configured display name may improve presentation, but it is not the authority.

### Keep Git authorship separate from decision ownership

These are separate facts:

```text
who discussed the change
who proposed the decision
who accepted it
who reviewed it
who implemented it
who authored the commit
who committed or merged it
```

Do not infer that the commit author made the product or design decision.

### Index old commit metadata

Index the complete metadata and message body of all reachable commits.

Do not fully parse and graph every historical tree immediately.

Use tiered historical indexing.

### Do not upload the whole repository for every MCP call

On first use:

```text
identify repository
synchronize missing Git objects
resolve revision
```

On later calls:

```text
send repository ID
send commit or workspace ID
```

For local changes:

```text
send patch
or push a temporary namespaced ref
```

---

# 1. Architecture

```text
Claude Code
    |
    v
Local Beagle MCP bridge
    - finds repository root
    - reads Git state
    - authenticates with JWT
    - syncs missing commits
    - sends local patches
    |
    v
Shared Beagle API
    - validates JWT
    - authorizes repositories
    - resolves revisions
    - serves indexes
    - stores decisions and feedback
    |
    +----------------------+
    |                      |
    v                      v
Git mirror service    Job queue
    |                      |
    v                      v
Bare repositories     Indexing workers
                      - Python/Frappe
                      - JS/TS/Vue
                      - dependencies
                      - commit deltas
                      - historical indexes
    |
    v
PostgreSQL + object storage
```

## Main components

### API service

Responsibilities:

```text
JWT validation
authorization
repository management
revision resolution
query API
decision and feedback writes
audit logging
```

### Git mirror service

Responsibilities:

```text
bare Git repositories
fetch from upstream
authenticated push for missing objects
branch and tag tracking
workspace refs
```

### Index workers

Responsibilities:

```text
commit indexing
dependency acquisition
source extraction
relationship resolution
change comparison
historical on-demand indexing
```

### Local MCP bridge

Responsibilities:

```text
authenticate user
detect local repository
sync missing commits
create overlays
call remote Beagle tools
fall back to local standalone mode
```

---

# 2. Core data model

```text
Organization
User
JwtTokenRecord
Repository
RepositoryAccess
GitIdentity
GitCommit
GitRef
CommitParent
IndexSnapshot
IndexArtifact
DependencyEnvironment
DependencyPackage
DependencyArtifact
DependencySnapshot
WorkspaceOverlay
McpSession
ChangeEpisode
Decision
DecisionActor
Feedback
TestResult
IndexJob
AuditEvent
```

---

# 3. Authentication and authorization

## JWT minting

The service should provide a simple authenticated administrative flow:

```text
administrator creates or invites user
service creates user record
service mints JWT
user stores token locally
```

Initial implementation may use manually created users and tokens.

No OAuth provider is required.

## Token properties

Use:

```text
signed JWT
expiry
token ID
scopes
organization
repository permissions
```

Prefer short-lived tokens where practical.

For CLI convenience, a longer-lived developer token may be allowed, but it should:

```text
be revocable
have repository scopes
have explicit permissions
have an expiry
```

## Validation

On every request:

1. verify signature;
2. verify expiry;
3. verify token ID is not revoked;
4. load user;
5. verify organization;
6. verify repository permission;
7. record audit event.

## Permissions

Start with:

```text
source:read
repo:register
repo:sync
workspace:create
workspace:share
decision:read
decision:write
feedback:read
feedback:write
admin:identity
```

## User-local configuration

Example:

```toml
service_url = "https://beagle.internal"
profile = "tanmoy"
token_keyring_name = "beagle-frappe"

[defaults]
organization = "frappe"
auto_sync_head = true
auto_upload_dirty_patch = false
include_untracked = "ask"

[privacy]
share_session_summary = true
share_raw_transcript = false
```

The profile name is only a local label.

The JWT subject is the authenticated identity.

---

# 4. MCP session identity

Create an MCP session when Claude Code connects.

```text
McpSession
```

Fields:

```text
id
user_id
organization_id
repository_id
client_name
client_version
started_at
ended_at
initial_revision
current_revision
workspace_id
privacy_mode
```

## Per-tool context

Every tool call records:

```text
user
session
repository
resolved commit
workspace
tool name
timestamp
request ID
```

Do not store complete raw parameters when they may contain secrets.

Store a redacted summary or hash where appropriate.

## Decision attribution

When a user discusses or accepts a decision through MCP, record the authenticated user as:

```text
speaker
proposer
approver
reviewer
decision owner
```

Only assign a role supported by the conversation or explicit confirmation.

---

# 5. Git identities

## Preserve historical metadata

For every commit, preserve exactly:

```text
author name
author email
author timestamp and timezone
committer name
committer email
committer timestamp and timezone
```

## GitIdentity

```text
name
email
verified_user_id
verification_method
first_seen
last_seen
```

One user may have several Git identities.

A historical identity may remain unclaimed.

## Mapping

Allow:

```text
verified email match
administrator mapping
explicit user claim
organization directory match
```

Do not map identities only by display-name similarity.

## Role distinction

Present clearly:

```text
Decision proposed by Tanmoy.
Decision approved by Alice.
Implemented in commits authored by Bob.
Merged by Carol.
```

Do not simplify this to:

```text
Bob decided it.
```

---

# 6. Repository storage

## Bare mirrors

Store repositories as:

```text
repositories/<repository-id>.git
```

Use Git objects as the canonical source store.

## Repository ingestion

Support:

```text
remote Git URL
GitHub/GitLab webhook
manual fetch
uploaded archive
local-only repository push
```

An uploaded archive becomes a synthetic revision identified by content hash.

## Small Git service

Expose authenticated Git Smart HTTP.

Use it only for:

```text
fetching missing objects
pushing local-only commits
pushing workspace refs
retrieving indexed revisions
```

Do not build a full Git hosting product.

## Ref namespaces

Use separate namespaces:

```text
refs/beagle/upstream/heads/<branch>
refs/beagle/upstream/tags/<tag>
refs/beagle/users/<user-id>/heads/<branch>
refs/beagle/workspaces/<user-id>/<workspace-id>
```

Users must not push directly to canonical upstream refs through Beagle.

Canonical refs are updated by:

```text
trusted fetch
webhook processing
authorized mirror job
```

---

# 7. Repository synchronization

## First MCP request

The local bridge sends:

```text
remote fingerprints
current branch
HEAD commit
dirty-state fingerprint
lockfile fingerprints
```

The service returns:

```text
repository ID
whether HEAD exists
whether snapshot is ready
required sync action
```

## Existing commit

If the service already has the commit:

```text
do not upload source
use existing snapshot
```

## Missing commit

Push only missing Git objects to a user-owned ref.

Let Git negotiate missing objects.

Do not build a custom object-transfer protocol.

## Dirty working tree

Use one of:

```text
patch overlay
temporary synthetic commit
local-only overlay
```

Default to patch overlay.

## Later MCP requests

Send:

```text
repository ID
revision or workspace ID
MCP session ID
```

Do not upload the codebase again.

## Resync conditions

Resync when:

```text
HEAD changes
branch changes
dirty fingerprint changes
manifest or lockfile changes
service reports missing objects
```

---

# 8. Commit and branch indexing

## Index commits, not branches

Example:

```text
A---B---C---D develop
         \
          E---F feature
```

Index:

```text
A
B
C
D
E
F
```

Commit `C` is reused by both branches.

## Parent-first processing

For newly fetched commits:

1. discover missing commits;
2. sort parent-first;
3. ensure a parent snapshot;
4. index changed files;
5. update dependency snapshot;
6. resolve affected relationships;
7. create immutable snapshot;
8. mark ready.

## Normal commit

```text
parent snapshot
+ tree diff
+ dependency changes
= child snapshot
```

Reuse unchanged artifacts.

## Merge commit

Use the actual merge tree.

Do not union the parent graphs.

Initial approach:

1. first parent as baseline;
2. diff first parent against merge tree;
3. reindex changed files;
4. re-resolve affected relationships;
5. record all parent links;
6. verify snapshot against merge tree.

## Force push

When a branch is rewritten:

```text
update branch pointer
retain commits still referenced elsewhere
mark unreachable commits
apply retention later
preserve decisions and history
```

---

# 9. Historical commit metadata

## Index all reachable commit metadata

On repository registration:

1. walk configured refs;
2. store every reachable commit;
3. store complete messages;
4. store authors and committers;
5. store parents;
6. parse trailers;
7. store timestamps;
8. index for search.

## Fields

```text
commit SHA
tree SHA
parent SHAs
subject
complete body
message encoding
author metadata
committer metadata
signature status
merge status
diff statistics
```

## Trailers

Parse:

```text
Co-authored-by
Signed-off-by
Reviewed-by
Acked-by
Fixes
Refs
Issue
Beagle-Decision
```

Preserve unknown trailers.

Trailers are evidence, not verified user mappings.

## Commit search

Index:

```text
subject
body
author
committer
trailers
issue references
changed paths
```

This should be available before full historical code indexing finishes.

---

# 10. Historical indexing tiers

## Tier 0 — all commit metadata

For every reachable commit:

```text
message
author
committer
timestamps
parents
trailers
statistics
ref reachability
```

## Tier 1 — active full snapshots

Fully index:

```text
default branch head
active branch heads
open review heads
release tags
recent merge commits
```

## Tier 2 — entity deltas

For important history:

```text
diff-to-entity mapping
relationship changes
DocType changes
hook changes
lifecycle changes
test changes
```

## Tier 3 — on-demand historical snapshots

When an old revision is queried:

```text
index missing tree
cache snapshot
return source-backed context
```

## Summary generation

Do not generate summaries for every old commit.

Generate them for:

```text
merge commits
release ranges
change episodes
requested commit ranges
substantial historical changes
```

---

# 11. Dependency analysis

## Goal

Index exact Python and JavaScript dependencies for each revision.

This allows Beagle to continue across boundaries such as:

```text
Press → Frappe
project → requests
frontend → Vue package
```

## Dependency snapshot identity

```text
repository
commit
runtime profile
platform
dependency groups
extras
package-manager configuration
```

Example:

```text
python=3.13
platform=linux-x86_64
groups=default,test
node=24
workspace=root
```

## Python manifests

Inspect:

```text
pyproject.toml
requirements files
constraints files
uv.lock
poetry.lock
Pipfile.lock
pylock.toml
setup.cfg
statically readable setup.py
editable apps
```

Prefer lockfiles.

## JavaScript manifests

Inspect:

```text
package.json
package-lock.json
npm-shrinkwrap.json
pnpm-lock.yaml
yarn.lock
workspace definitions
Git dependencies
local file dependencies
```

Prefer the repository's active lockfile.

---

# 12. Safe dependency acquisition

## Security rule

Never execute dependency code during indexing.

Do not run:

```text
pip install
Python build backends
setup.py
npm install scripts
preinstall
postinstall
prepare
package binaries
```

## Python

Preferred order:

1. exact artifact and hash from lockfile;
2. download compatible wheel without installing;
3. otherwise download source distribution;
4. safely unpack;
5. index source and stubs;
6. record incomplete metadata where needed.

Index from wheels:

```text
.py
.pyi
metadata
entry points
top-level package map
```

Do not load compiled extensions.

## JavaScript

Preferred order:

1. resolve exact version and integrity from lockfile;
2. fetch registry tarball or pinned Git source;
3. verify integrity;
4. safely unpack;
5. index shipped source.

Index:

```text
.js
.mjs
.cjs
.ts
.d.ts
.vue
package.json
exports
types metadata
source maps
```

Do not depend on an existing `node_modules`.

## Local apps and workspaces

Link local packages to repository revisions.

Do not duplicate them as downloaded dependencies.

## Archive safety

Enforce:

```text
size limits
file-count limits
path traversal protection
unsafe symlink rejection
hash verification
unprivileged extraction
disposable workspace
network disabled after download
```

---

# 13. Dependency graph

## Entities

```text
DependencyEnvironment
PackageRelease
PackageArtifact
ImportableModule
ExportedSymbol
PackageDependency
RepositoryDependency
```

## Relationships

```text
REQUIRES_PACKAGE
RESOLVES_TO_RELEASE
PROVIDES_MODULE
IMPORTS_DEPENDENCY
CALLS_DEPENDENCY_SYMBOL
EXTENDS_DEPENDENCY_CLASS
IMPLEMENTS_PROTOCOL_FROM
RAISES_DEPENDENCY_EXCEPTION
WORKSPACE_DEPENDS_ON
LOCAL_APP_DEPENDS_ON
```

## Provenance

Every dependency symbol stores:

```text
package
version
artifact hash
source type
runtime profile
repository commit
indexer version
```

## Cross-package resolution

Example:

```python
from frappe.model.document import Document

class Site(Document):
    ...
```

Resolve:

```text
press.Site
  INHERITS
frappe.Document
```

Then continue into the exact Frappe version for:

```text
Document.save
lifecycle behavior
exceptions
callbacks
```

## Context ranking

Default order:

```text
project code
direct dependency API
important direct dependency implementation
transitive dependency implementation
```

Do not dump dependency internals unless they affect the question.

---

# 14. Dependency caching

Cache artifacts by:

```text
ecosystem
package
version
artifact hash
```

Public artifacts may be shared globally.

Private artifacts remain organization-scoped.

Separate:

```text
package source facts
repository-specific usage edges
```

When lockfiles change:

1. calculate dependency delta;
2. download new artifacts;
3. reuse unchanged artifacts;
4. remove obsolete usage edges;
5. re-resolve imports;
6. summarize dependency changes.

---

# 15. Workspace overlays

## WorkspaceOverlay

Fields:

```text
id
user_id
repository_id
base_commit
patch hash
dirty-tree hash
created_at
updated_at
expiry
sharing state
```

## Overlay behavior

```text
base snapshot
+ local patch
+ local dependency changes
= workspace snapshot
```

## Ownership

A workspace belongs to the authenticated user.

Other users need explicit sharing permission.

## Local-only mode

For sensitive changes:

```text
download base index
apply changes locally
run local MCP
upload nothing
```

---

# 16. Decision and change memory

Use change episodes spanning:

```text
one or more MCP sessions
one or more commits
one or more decisions
one or more feedback items
```

## Decision record

```text
problem
goal
constraints
decision
rationale
alternatives
status
actors
affected entities
workspace
commits
tests
risks
follow-ups
```

## DecisionActor

Fields:

```text
decision
user or external identity
role
confidence
evidence
confirmation state
```

Roles:

```text
speaker
proposer
decision owner
approver
reviewer
implementer
summary editor
```

## Commit authorship

Attach separately:

```text
commit author
committer
merge actor
```

Never use commit authorship as proof of decision ownership.

---

# 17. Session summaries

## Raw conversation

Keep raw transcripts local by default.

Store remotely:

```text
redacted summary
confirmed decisions
affected entities
workspace or commits
tests
follow-ups
```

The bridge may store:

```text
transcript path
transcript hash
local session ID
```

without uploading the raw transcript.

## Session summary

Suggested sections:

```text
Problem
Discussion
Decision
Rationale
Rejected alternatives
Changes made
Tests
Risks
Follow-ups
```

## Attribution

All direct statements recorded from the MCP session use the authenticated JWT user as speaker.

If another person is mentioned, record them as an external named participant unless independently authenticated or verified.

---

# 18. Feedback memory

Record:

```text
comment
author
revision
entity
diff range
status
rationale
resulting commit
reusable lesson
```

Statuses:

```text
received
accepted
implemented
rejected
superseded
```

Do not convert every comment into a permanent rule.

Promote feedback only when:

```text
explicitly confirmed
repeated
encoded in tests
accepted as project policy
```

---

# 19. Revision comparison

For two revisions, return:

```text
changed files
changed entities
changed calls
changed dependencies
DocType changes
hook changes
lifecycle changes
tests
decisions
feedback
authors and committers
```

## Branch comparison

Use:

```text
merge base
source head
target head
```

Return source and target changes separately.

## Merge summary

When a merge commit exists, analyze the merge result tree.

Do not assume the source branch diff exactly equals merged behavior.

---

# 20. Historical retrieval

Beagle should answer:

```text
Who proposed this change?
Who approved it?
Who authored the commit?
Who merged it?
Why was this function changed?
What did the commit message say?
Which decision episode affected this field?
What was rejected?
Was the decision superseded?
Which dependency version was active?
```

## Ranking

Rank history by:

```text
exact entity change
same field or hook
same lifecycle path
commit-message relevance
decision confirmation
commit ancestry
recency
```

## Context limits

Default to:

```text
3–5 relevant commits
compact metadata
message body only when useful
decision summary before raw historical detail
```

---

# 21. API and MCP

Every source operation must be revision-aware.

## Repository

```text
identify_repository
sync_status
register_repository
index_revision
index_status
```

## Code intelligence

```text
search
resolve
describe
relations
trace
investigate
context
```

## Dependencies

```text
dependency_snapshot
dependency_search
dependency_describe
```

## Workspaces

```text
create_workspace
update_workspace
share_workspace
delete_workspace
```

## History

```text
commit_history
search_commit_messages
entity_history
compare_revisions
decision_history
feedback_history
```

## Identity

```text
current_user
list_git_identities
claim_git_identity
confirm_decision_actor
```

Git objects should move through Git Smart HTTP, not JSON MCP payloads.

Every response should include:

```text
user
repository
resolved commit
workspace
dependency snapshot
index status
```

---

# 22. Storage

Use PostgreSQL for:

```text
users
organizations
permissions
repositories
commits
refs
snapshot metadata
sessions
decisions
feedback
jobs
audit logs
```

Use object storage for:

```text
source artifacts
dependency archives
index artifacts
snapshot manifests
reports
```

Use bare Git repositories for:

```text
Git objects
refs
historical trees
```

Use SQLite for:

```text
standalone mode
worker scratch
tests
downloadable bundles
```

---

# 23. Security and privacy

## Source upload consent

Do not upload code silently.

Repository registration must be explicit.

After registration, incremental synchronization may follow organization policy.

## Secrets

Protect:

```text
JWTs
Git credentials
registry credentials
private packages
source code
workspace patches
session summaries
commit messages
```

## Commit messages

Commit bodies may contain sensitive data.

Store them under repository permissions.

Run secret detection before injecting them into Claude context.

Preserve the original Git object unchanged.

## Audit events

Record:

```text
who synced a repository
who pushed a workspace
who queried source
who created a decision
who confirmed a decision
who mapped a Git identity
who shared a workspace
```

---

# 24. Implementation phases

## Phase A — JWT identity

- [x] Add users and organizations.
- [x] Mint signed JWTs.
- [x] Add expiry and revocation.
- [x] Add repository permissions.
- [x] Store JWT securely in local bridge. *(bridge TokenStore: env → 0600 file → optional keyring; never in repo)*
- [x] Create MCP session records.
- [x] Add request audit context.
- [x] Reject unauthenticated writes.

## Phase B — Git repository service

- [x] Store bare repositories.
- [x] Register remotes.
- [x] Fetch upstream refs.
- [x] Expose authenticated Smart HTTP.
- [x] Add canonical and user ref namespaces.
- [x] Add integrity checks.
- [x] Add push and fetch authorization.

## Phase C — commit metadata

- [x] Index all reachable commit metadata.
- [x] Store full subjects and bodies.
- [x] Store authors, committers, timestamps, and timezones.
- [x] Store parent graph.
- [x] Parse trailers.
- [x] Store signature status.
- [x] Build commit-message search. *(portable LIKE scan; FTS is a later optimization)*

## Phase D — revision indexing

- [x] Index commits parent-first. *(rev-list --reverse --topo-order)*
- [x] Reuse shared ancestors. *(snapshots keyed by repository+commit; reused, never re-indexed)*
- [x] Support merge commits. *(merge result tree materialized and indexed as-is)*
- [x] Support force pushes. *(snapshots immutable by commit; survive branch rewrite — GC of unreferenced snapshots deferred)*
- [x] Add snapshot manifests. *(index_snapshots: counts, indexer version, status, artifact path)*
- [x] Include revision in every result. *(snapshot search responses carry the commit sha)*

Approach: materialize the commit tree (tracked files only, no checkout/execution)
and reuse the existing local index engine, storing each commit's index as an
immutable artifact. Delta-from-parent reuse and entity deltas (Tier 2) are a
later optimization; snapshots are currently full per commit.

## Phase E — dependency analysis

- [x] Parse Python manifests and lockfiles. *(uv.lock, poetry.lock, pylock.toml, requirements.txt)*
- [x] Parse JavaScript manifests and lockfiles. *(package-lock.json v2/v3, pnpm-lock.yaml, yarn.lock v1, package.json)*
- [x] Download exact artifacts. *(PyPI JSON index + npm registry; fetch overridable for tests)*
- [x] Verify hashes. *(sha256 hexdigest and npm sha512-base64 integrity)*
- [x] Safely unpack. *(size/file-count limits, path-traversal + symlink rejection, tar/zip)*
- [x] Index Python and JS source. *(downloaded artifact indexed by the engine, cached by hash)*
- [x] Resolve imports and inheritance across packages. *(Python: import + symbol resolution with provenance; JS symbol edges remain a follow-up)*
- [x] Cache by artifact hash. *(artifact unpacked + indexed once per hash, reused across repositories)*
- [x] Run no package scripts. *(parsing + verified unpack + static indexing only; no install/build/lifecycle execution)*

Cross-package *symbol* resolution is implemented for Python (the design's
press→frappe example): a project import resolves to the exact dependency version
that provides the module, and imported symbols resolve to entities in that
version, with package/version/hash provenance. JavaScript artifacts are
downloaded, verified, and indexed; resolving JS symbol edges across packages is
the remaining follow-up.

## Phase F — local bridge

- [x] Discover repository. *(reuses find_repo_root)*
- [x] Read JWT from keyring. *(env -> 0600 file -> optional keyring)*
- [x] Perform sync handshake. *(sync-status: has_commit / has_snapshot)*
- [x] Push only missing commits. *(git push to the user's own ref namespace, only when absent)*
- [x] Send dirty patches as overlays. *(beagle-bridge sync --upload-dirty creates a WorkspaceOverlay)*
- [x] Detect local changes.
- [x] Support local-only mode. *(uploads nothing)*
- [x] Avoid repeated uploads. *(already-synced commit and snapshot upload nothing)*

## Phase G — identity mapping

- [x] Store Git identities.
- [x] Support verified mappings. *(email auto-map, admin map, explicit claim)*
- [x] Support several emails per user.
- [x] Keep ambiguous identities unclaimed.
- [x] Parse co-author and review trailers.
- [x] Keep decision roles distinct from commit roles. *(commit roles are identity evidence; decision roles are Phase H)*

## Phase H — decisions and feedback

- [x] Record session summaries. *(redacted via temporal secret scrubber; raw transcript stays local)*
- [x] Add change episodes.
- [x] Add DecisionActor.
- [x] Add explicit confirmation. *(inferred by default; confirm_actor promotes to confirmed)*
- [x] Link workspaces and commits. *(decisions carry workspace_id + commit_sha columns; affected entities linked)*
- [x] Add feedback states. *(received/accepted/implemented/rejected/superseded)*
- [x] Retrieve history by entity. *(decisions and feedback queryable by entity id)*
- [x] Label inferred attribution. *(authenticated author = confirmed proposer; mentioned others = inferred)*

## Phase I — comparison and consumers

- [x] Compare revisions. *(changed files + entity add/remove/change + commit range + authors)*
- [x] Summarize branch changes. *(source vs target around the merge base)*
- [x] Summarize merges. *(first parent vs merge result tree)*
- [x] Add Claude Code MCP. *(read-only beagle-service-mcp forwarding to the service via the bridge)*
- [x] Add CI integration. *(beagle-bridge ci base head — comparison report, --json)*
- [x] Add local-change context. *(workspace overlays + beagle-bridge sync --upload-dirty)*
- [x] Add lightweight administration UI. *(read-only /admin page + /v1/admin/overview)*

---

# 25. Benchmarks

## Authentication and identity

Cases:

```text
one user, one Git email
one user, several Git emails
same display name, different users
unclaimed historical author
MCP speaker differs from commit author
author differs from committer
group decision
```

Targets:

```text
Authenticated speaker attribution          = 100%
False Git identity mapping                 = 0
Commit author shown as decision owner
without evidence                            = 0
Confirmed decision actor accuracy           = 100%
```

## Commit history

Targets:

```text
Reachable commit recall                     = 100%
Message subject/body fidelity               = 100%
Author/committer fidelity                   = 100%
Parent graph fidelity                       = 100%
Trailer parsing precision                   >= 99%
```

## Synchronization

Requirements:

```text
Full repository re-upload per MCP call      = 0
Missing commit synchronization              = 100%
Wrong repository acceptance                 = 0
Cross-user workspace leakage                = 0
```

## Multi-branch

Requirements:

```text
revision isolation                          = 100%
cross-branch fact leakage                    = 0
shared commit reuse                          = 100%
merge snapshot matches merge tree            = 100%
```

## Dependency analysis

Targets:

```text
Locked version precision                    = 100%
Artifact integrity verification             = 100%
Direct dependency recall                    >= 99%
Transitive dependency recall                >= 98%
Cross-package symbol precision              >= 95%
Wrong-version source returned               = 0
Executed package scripts                    = 0
```

## Historical retrieval

Targets:

```text
Relevant commit in top 5                    >= 95%
Relevant decision in top 3                  >= 90%
Role distinction correctness                = 100%
Irrelevant historical context               <= 20%
```

---

# 26. Risks

## JWT leakage

Mitigation:

```text
keyring storage
expiry
revocation
scoped permissions
audit logs
```

## Misattribution

Mitigation:

```text
separate role types
verified Git mappings
explicit confirmation
confidence and evidence
```

## Silent source upload

Mitigation:

```text
explicit registration
visible sync status
organization policy
local-only mode
```

## Repeated upload cost

Mitigation:

```text
Git negotiation
commit identity
session handshake
patch overlays
artifact hashes
```

## Dependency execution

Mitigation:

```text
download only
no builds
no lifecycle scripts
isolated workers
archive safety
```

## Historical noise

Mitigation:

```text
tiered indexing
relevant-history ranking
summary generation only when useful
token budgets
```

## Sensitive commit messages

Mitigation:

```text
repository permissions
secret detection
redacted Claude context
original Git data preserved
```

---

## Recommended first delivery

Build this first:

```text
one organization
server-minted JWT users
one private Git repository
bare Git mirror
full commit metadata indexing
multiple branch heads
parent-first commit indexing
Python dependency snapshot
Frappe local dependency resolution
local MCP bridge
missing-commit Git synchronization
dirty patch overlay
authenticated session identity
decision actor tracking
shared change summaries
```

Add JavaScript dependency indexing after the Python dependency path is stable.

Do not add automated review or adaptation until:

```text
revision isolation is correct
identity attribution is trustworthy
Git synchronization is reliable
dependency versions are reproducible
decision summaries are tied to exact commits
```

---

## Definition of done

This plan is complete when Beagle can:

- authenticate each MCP user through a server-minted JWT;
- record the authenticated speaker for every session;
- preserve Git author and committer identity separately;
- distinguish decision makers, reviewers, implementers, and commit authors;
- index all historical commit messages and metadata;
- mirror and synchronize repositories through Git;
- avoid uploading the full repository for every question;
- index multiple branches without duplicating shared commits;
- incrementally index pushed changes;
- support local dirty overlays;
- index exact Python and JavaScript dependency source safely;
- resolve project code into the correct dependency versions;
- store shared decisions, summaries, and feedback;
- answer who changed something, who decided it, what changed, and why;
- prevent identity, branch, repository, and dependency facts from leaking across scopes.
