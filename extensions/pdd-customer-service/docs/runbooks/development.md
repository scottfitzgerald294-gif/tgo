# PDD Customer Service Development Runbook

## 1. Current Scope

Phase 3 established the independent Python project and process health endpoint.
Phase 5 added the synthetic PDD message simulator. Phase 6 adds an
extension-owned SQLite Inbox/Outbox/Audit ledger, local idempotency, retries,
dead letters, per-conversation locking, minimal AI/human reply leases, and
restart recovery. The application still does not connect to real PDD, TGO
business APIs, a production database, a knowledge service, or a model provider.

Runtime endpoints are:

```text
GET /health
200 {"status":"healthy","service":"pdd-customer-service"}

POST /simulator/messages
GET /simulator/shops/{shop_id}/buyers/{buyer_id}/conversations/{conversation_id}
```

The health endpoint is a process-level readiness signal. It intentionally makes
no external calls so infrastructure failures cannot make the process itself
unobservable.

Use the repository-level
[`PDD simulator runbook`](../../../../docs/runbooks/pdd-simulator.md) for
synthetic POST/GET examples, expected results, limitations, and troubleshooting.

Use the repository-level
[`message reliability runbook`](../../../../docs/runbooks/message-reliability.md)
for SQLite state, retries, replay-window handling, human ownership, recovery,
503 behavior, and safe inspection.

## 2. Prerequisites

- Python 3.11
- Poetry 2.x
- GNU Make
- Git

Install dependencies only inside this project environment:

```bash
cd extensions/pdd-customer-service
poetry install --with dev
```

Do not install or configure a PDD SDK, model SDK, production database, queue, or
browser automation tool. Phase 6 uses only Python's standard-library SQLite and
adds no dependency or Docker service.

If the host does not provide the required Python version or development tools,
use an isolated Python 3.11 development container. Do not replace the project's
Python requirement with an unsupported system interpreter, and do not change
system security settings to make the checks pass.

## 3. Environment Safety

The service does not require a `.env` file for the health endpoint. If a future
local-only phase needs one:

```bash
cp .env.example .env
```

Rules:

- Keep `.env` local; Git must ignore it.
- Keep every value in `.env.example` empty.
- Use secret references rather than secret values in shareable configuration.
- Never paste real PDD, TGO, model, database, buyer, or production credentials
  into the repository, tests, fixtures, logs, screenshots, or issue reports.
- `PDD_INTEGRATION_ENABLED` and `TGO_INTEGRATION_ENABLED` must remain unset for
  the local simulator.
- `PDD_RELIABILITY_DB_PATH` may point only to a local development SQLite file;
  never commit the file or put credentials, URLs, or production paths in the
  value.

Verify the ignore rule without creating a file:

```bash
git check-ignore -v .env
```

## 4. Start and Check the Service

Start the local process:

```bash
make run
```

The command binds to `127.0.0.1:8091`. Check it from another terminal:

```bash
curl --fail http://127.0.0.1:8091/health
```

Expected response:

```json
{"status":"healthy","service":"pdd-customer-service"}
```

Starting the health and simulator service must not produce outbound network
traffic.

## 5. Development Commands

Run commands from `extensions/pdd-customer-service/`:

```bash
make format
make lint
make test
make test-unit
make test-integration
make security-check
```

Command responsibilities:

| Command | Purpose |
|---|---|
| `make format` | Apply Ruff formatting to application and test code |
| `make lint` | Check formatting, Ruff rules, and strict mypy types |
| `make test` | Run every collected test |
| `make test-unit` | Run isolated unit tests |
| `make test-integration` | Run in-process integration tests without external network |
| `make security-check` | Run Bandit, dependency audit, and `.env` ignore verification |

Never suppress a failure, exclude a failing test, or lower a rule merely to
obtain a successful command.

## 6. Test-First Workflow

Every behavior change follows this sequence:

1. Add one focused automated test for the required behavior.
2. Run the focused test and confirm it fails for the expected missing behavior.
3. Commit or otherwise preserve the RED evidence.
4. Add the smallest implementation that satisfies the test.
5. Run the focused test, its full test category, and `make test`.
6. Run formatting, lint, and security checks before committing.

Tests must use synthetic data. Unit and integration tests may not open external
network connections. Reliability tests use temporary SQLite files and
deterministic clocks. Future real adapters require approved contract tests
before any production implementation.

## 7. Directory Ownership

| Path | Responsibility |
|---|---|
| `app/api/` | FastAPI transport routes |
| `app/adapters/pdd/` | Reserved official PDD protocol boundary |
| `app/services/` | Connector use-case orchestration |
| `app/clients/` | Typed clients for approved service contracts |
| `app/models/` | Typed internal and transport models |
| `app/repositories/` | Connector-owned persistence interfaces |
| `tests/unit/` | Isolated behavior tests |
| `tests/integration/` | In-process component tests using fakes |
| `tests/contract/` | Approved external contract tests |
| `tests/fixtures/` | Synthetic, non-sensitive test data |
| `config/pdd/` | Reviewed non-secret configuration |
| `knowledge/` | Reviewed knowledge manifests |
| `evals/` | Reproducible quality and safety evaluations |

Code in this extension may use documented TGO APIs. It must not import TGO
service internals or access TGO databases directly.

## 8. Failure Handling

- If a test, lint, type, security, or dependency audit fails, stop and retain
  the failure output.
- Diagnose the root cause; do not automatically weaken configuration.
- If verification needs real PDD details, credentials, a real model, or a TGO
  core modification, stop and request a separately approved phase.
- Do not tag a phase complete until every required check succeeds and the Git
  worktree is clean.
