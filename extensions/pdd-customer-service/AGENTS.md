# PDD Customer Service Extension Rules

## Scope

This directory is the concrete implementation root for the independent PDD
Connector described in `docs/architecture/`. It owns only integration-boundary
concerns. TGO remains the system of record for visitors, sessions, staff,
queues, agents, RAG, WuKongIM, and the browser workbench.

Phase 3 contains only the project skeleton and a dependency-free health
endpoint. All adapters, clients, services, repositories, configuration,
knowledge, and evaluation directories are placeholders unless a later approved
phase assigns behavior to them.

## Architecture

- `app/api/`: HTTP routes and transport models.
- `app/adapters/pdd/`: PDD protocol boundary. No protocol may be guessed.
- `app/services/`: Connector application orchestration.
- `app/clients/`: Typed clients for approved external contracts.
- `app/models/`: Internal typed models; never expose unvalidated bare mappings.
- `app/repositories/`: Connector-owned persistence interfaces.
- `tests/unit/`: Isolated behavior tests without network or infrastructure.
- `tests/integration/`: In-process component tests using fakes.
- `tests/contract/`: Approved PDD and TGO contract tests.
- `tests/fixtures/`: Synthetic, non-sensitive test data only.
- `config/pdd/`: Non-secret, reviewed PDD configuration only.
- `knowledge/`: Reviewed knowledge-source manifests, never production secrets.
- `evals/`: Reproducible response-quality and safety evaluations.

The extension may call documented TGO APIs. It must never read or write a TGO
service database directly. PDD credentials and protocol handling must never be
placed in `repos/*`.

## Code Standards

- Target Python 3.11 and use explicit type annotations.
- Use FastAPI and Pydantic v2 patterns already present in TGO services.
- Do not use bare `dict` in business interfaces; define typed models.
- Keep imports side-effect free. Importing the application must not contact the
  network, a database, PDD, TGO, or a model provider.
- Use dependency injection at external boundaries so tests can use fakes.
- Never hardcode credentials, tokens, environment URLs, buyer data, or PDD
  protocol fields.
- Log only allow-listed structured fields. Never log secrets, raw credentials,
  full personal data, prompts, or unredacted external payloads.
- Keep the first version text-only and default to human handoff whenever a
  future decision cannot be proven safe.

## Test-First Workflow

Every feature, bug fix, endpoint, service method, adapter behavior, repository
behavior, and security rule must have an automated test that is observed
failing for the expected reason before production code is written.

1. Add one focused test.
2. Run it and confirm the expected failure.
3. Add the smallest implementation that makes it pass.
4. Run the focused test and the full relevant suite.
5. Refactor only while all tests remain green.

Required commands:

```bash
make format
make lint
make test
make test-unit
make test-integration
make security-check
```

Contract tests become mandatory before any real PDD or TGO network adapter is
implemented. Integration tests in Phase 3 must remain in-process and must not
make external network calls.

## Prohibited Actions

- Do not connect to real PDD endpoints, accounts, webhooks, or credentials.
- Do not connect to real model, embedding, or reranking providers.
- Do not invent PDD URLs, fields, event names, signatures, encryption,
  acknowledgements, rate limits, or error codes.
- Do not scrape, automate a browser, or reverse engineer private PDD protocols.
- Do not modify TGO core business code under `repos/*`.
- Do not bypass the Connector for PDD inbound or outbound traffic.
- Do not commit `.env`, secrets, private keys, logs, caches, local databases,
  production payloads, or buyer personal data.
- Do not weaken or skip failing tests, lint, type, or security checks.
- Do not add dependencies without a concrete requirement and security review.

If a task requires any prohibited action, stop and request a separately
approved phase rather than implementing it.
