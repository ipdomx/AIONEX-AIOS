# Phase 22C — Single Cloud Provider Controlled Sandbox

## Current status

Phase 22C completed a real, controlled OpenAI execution successfully on 2026-08-05.

The run used `gpt-5-mini`, exactly six sequential provider requests, no retries, no fallback, and no production modification. It produced six department artifacts plus the manifest, report, and three-way comparison under the isolated `/var/tmp` output root.

The cloud integration and execution path succeeded. The engineering review remained intentionally truthful: `approved=false` with readiness `0.82` because generated department artifacts did not claim that tests or required security reviews had actually been completed.

No API key, Authorization header, raw prompt, raw API response, project source code, user data, production secret, or runtime output directory was added to Git.

## Scope

Phase 22C connects exactly one cloud provider—OpenAI—to the existing six-department `EngineeringOrganization` through the existing `OpenAIProvider` adapter.

The sandbox explicitly forbids:

- local or cloud fallback providers;
- tools, web search, or external browsing;
- parallel requests;
- more than six API requests in one execution;
- more than one retry for a department;
- more than 1.00 USD total configured budget;
- more than 1,200 output tokens per request;
- nonzero temperature;
- endpoints other than the official OpenAI API;
- project `.env` files or secrets stored in repository content;
- writes outside an explicit absolute output root;
- direct production changes.

## Added implementation

`src/aios/cloud_provider_sandbox.py` provides:

### `Phase22CSecret`

- keeps the API key out of `repr`;
- exposes only a last-four helper when verification is necessary;
- is loaded only from `/root/.config/aionex/phase22c-openai.env`;
- requires a regular root-owned file with mode `600`;
- accepts only `OPENAI_API_KEY` and `AIOS_PHASE22C_MODEL`.

### `OpenAIOfficialHTTPTransport`

- accepts only `https://api.openai.com/v1/responses`;
- validates the configured model only through `https://api.openai.com/v1/models/{model}`;
- disables proxy inheritance;
- sends `store=false`;
- converts the existing `OpenAIProvider` structured-output metadata to the Responses API JSON-schema format;
- refuses tools and nonzero temperature;
- serializes all requests with one active request at a time;
- applies a timeout no greater than 180 seconds;
- enforces a hard request cap no greater than six;
- returns only normalized output, token usage, latency, model, and calculated cost fields;
- never stores or reports the Authorization header or API key;
- sanitizes HTTP errors to status/type/code without retaining response bodies.

### `CloudProviderSandbox`

- reuses the existing `OpenAIProvider` rather than creating another provider implementation;
- requires both `BudgetAccount` and `CostGovernor`;
- uses `ProviderPolicy` to allow only OpenAI for the project and explicitly blocks alternate providers;
- uses the provider rate limiter with one concurrent request;
- uses an internal retry policy of one transport attempt and controls the one allowed department retry itself;
- performs a closed-budget preflight for all six worst-case requests before the first API request;
- checks the remaining worst-case cost before each request;
- records actual token-derived cost after each completed API response;
- runs Architecture, Backend, Frontend, Security, Quality, and DevOps sequentially;
- validates strict JSON and exact acceptance-criterion coverage;
- passes the model booleans `tests_passed` and `security_reviewed` unchanged to `EngineeringOrganization`;
- creates six department artifacts, `manifest.json`, `REPORT.md`, `comparison.json`, and `COMPARISON_REPORT.md`;
- compares Offline Mock, saved qwen3:8b results, and OpenAI using the same deterministic structural heuristic;
- uses atomic writes, staging cleanup, path-containment checks, and duplicate-execution protection;
- invokes no shell command and imports no subprocess API.

## Budget model

The sandbox does not guess model pricing.

The execution harness must supply current, officially verified:

- input cost per million tokens;
- output cost per million tokens.

The model itself comes only from `AIOS_PHASE22C_MODEL` after availability is checked against the authenticated OpenAI account.

Before any API call, the sandbox verifies that six requests, each using the configured maximum input safety allowance and 1,200 output tokens, fit inside the 1.00 USD cap. If not, execution stops before spending.

The OpenAI Responses API reports token usage but not a direct per-response dollar charge. Therefore manifests distinguish:

- `reported_cost: null`;
- `calculated_cost`: token usage multiplied by the operator-verified model rates;
- `cost_basis`: an explicit description of that calculation.

## Request and evidence policy

The sandbox does not save:

- the API key;
- Authorization headers;
- raw API response objects;
- raw prompt strings;
- project source code;
- user data;
- production secrets.

Only validated department engineering artifacts are written to the output root. The prompt contains the project name, objective, department, and generic acceptance criteria only.

The model is instructed not to claim tests or security reviews that were not executed. Its boolean evidence is passed unchanged into the existing organization review.

## Manifest contract

A successful real run records:

- provider and actual configured model;
- execution network/key/cloud/fallback/production proof;
- total requests and retries;
- input, output, and total tokens;
- reported and calculated cost fields;
- budget cap and remaining balance;
- per-department and total latency;
- artifact hashes;
- schema validation and acceptance coverage;
- `approved`, `readiness_score`, blockers, and rework plan;
- the non-retention policy for prompts, raw API responses, headers, and keys.

## Comparison contract

The three-way comparison covers:

- artifact count;
- JSON validity;
- acceptance coverage;
- department specialization;
- actionable implementation detail;
- technical evidence density;
- risk clarity;
- cross-department repetition;
- time;
- tokens;
- calculated cost;
- readiness and approval;
- blockers and rework;
- truthful evidence behavior;
- quality per calculated cost when cost is nonzero.

The heuristic is deterministic and transparent, but it is not a substitute for human review.

## Test results

Required isolated suite:

- `99 passed`

Broader provider, routing, integration, organization, local sandbox, and offline sandbox suite:

- `107 passed`

Unit tests use fake transports and do not read the real secret or access the network.

Coverage includes:

- exact official endpoint validation;
- official model-availability endpoint;
- request serialization and request caps;
- required budget governor/account;
- pre-request budget rejection;
- strict JSON and schema failures;
- six departments and six artifacts;
- hashes and three-way comparison;
- truthful engineering review behavior;
- path traversal, duplicate execution, atomic writes, and staging cleanup;
- no fallback;
- no secret/header leakage;
- no shell or subprocess use.

## Real execution result

Controlled execution:

- provider: `openai`;
- model: `gpt-5-mini`;
- execution ID: `phase22c-openai-controlled-diagnostic-v2`;
- output directory: `/var/tmp/aionex-phase22c/sandbox-output/phase22c-openai-controlled-diagnostic-v2`;
- six department artifacts;
- six API requests;
- zero retries;
- 2,245 input tokens;
- 3,055 output tokens;
- 5,300 total tokens;
- calculated cost: `0.00667125 USD`;
- configured budget cap: `1.00 USD`;
- total duration: `50.278179` seconds;
- fallback used: `false`;
- production modified: `false`;
- execution network used: `true`;
- provider key used: `true`, without being returned or stored in evidence;
- raw prompts, raw responses, Authorization headers, and secrets returned: `false`.

Review result:

- approved: `false`;
- readiness score: `0.82`;
- quality comparison winner: `openai`.

The blockers are evidence blockers rather than transport or sandbox failures. Department artifacts correctly reported that their test plans and required security reviews had not been executed. The rework plan therefore requires completing those tests and security reviews before engineering approval.

Three-way comparison:

- Offline Mock: approved `true`, readiness `1.0`, duration approximately `0.0113` seconds, zero token cost;
- retained local qwen3:8b: approved `false`, readiness `0.82`, duration approximately `1456.4565` seconds;
- OpenAI: approved `false`, readiness `0.82`, duration approximately `50.2782` seconds, calculated cost `0.00667125 USD`.

Final validation after the GPT-5 transport compatibility and safe-diagnostic fixes:

- `101 passed`;
- no network request was sent by the patch scripts;
- production was not modified by the patch scripts;
- production remained healthy after the real execution.

The secret remains outside the repository at `/root/.config/aionex/phase22c-openai.env`, owned by root with mode `600`. Its value was never printed, returned, committed, or copied into runtime artifacts.

## Production boundary

No production file, Compose definition, environment file, database, network, or service was modified by the Phase 22C execution.

After the real provider run, Nginx, Backend, Frontend, Backup Worker, PostgreSQL, and Redis remained running and healthy; Cloudflared remained running.
