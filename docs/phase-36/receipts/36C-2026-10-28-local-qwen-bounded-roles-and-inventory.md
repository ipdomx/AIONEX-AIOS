# Phase36C real local Qwen Project AI durable task-bound and auto-refresh

2026-10-28 Asia/Riyadh / 2026-10-27 UTC.
AIONEX AIOS only; protected main 9b705c2309dce371014a6598c89acb033701d7bd.
Development candidate only; worker remains stopped until this change passes CI, is
merged and the real synthetic production durable queue canary is repeated.

## Real failing canary and exact remediation

A single synthetic, Free/zero-cost ProjectExecution (owned exclusively by a
temporary synthetic tenant) was admitted by the real production worker with a
connected and current validated Qwen2.5:1.5B Ollama model. The durable route,
provider reservation and four-role graph were created. The planner attempt ended
after 120.33 seconds with provider_unavailable and no completed model text or
charges. It was not an accepted customer deliverable.

Investigating the real worker showed its non-coder AI route used the general
provider adapter's 1,024-token default prediction count instead of the exact
planner/researcher/reviewer 192-token budget. Repeating the same synthetic
planner prompt on live Ollama, explicitly capping num_predict=192, produced 192
tokens in 7.42 seconds. The real local model was healthy and served tiny prompts.

This source change propagates the immutable route task max_tokens into each
ProjectAIInvocation and adds a dedicated Ollama-only non-coder adapter that
enforces num_predict equal to the task budget, with bounded context/CPU threads,
strict usage verification, 65-second transport deadline and no paid providers.
It deliberately does NOT change the general-purpose AI chat adapter.
The local JSON coder likewise inherits its **640-token** route-task budget
and a shorter 90-second HTTP deadline, matching the actual Qwen compact JSON
success (~181 output tokens), rather than allocating the general 1,024-token
unbounded completion on a single CPU lease. All schema/security checks stay.

## Evidence model policy and its lifetime

The four-role real local Ollama source proof generated a safe Task Manager
specification in 17.76 seconds of cumulative model responses; the reviewed
AIONEX compiler built 32 executable files, verified the generated source and
rollback archive, and ran six departmental governance reviews. Explicit Owner
and independent research release approval remains withheld correctly.

The new Qwen2.5:1.5B reviewed free model is admitted to the official launch
inventory rather than relying on an expiring one-off DB insertion. It has
zero price, offline-only privacy, task capability (coding, reasoning, research,
review), conservative operational concurrency one and 8 RPM. The previously
reviewed Gemma3:4B remains in the catalogue, but the default Free policy uses
Qwen, matching the Owner's current active live policy. Paid model policies
are unchanged. The existing six-hour official evidence-refresh observer must
be upgraded separately before the temporary Qwen evidence expires.

## Tests and launch boundaries

A separate disconnected Docker image suite passed 25 cases including the
existing structured Ollama/OpenAI provider request checks, nine bounded local
role limits and refusal cases, Free/Paid reviewed policy checks and zero-cost
default. This is source-level evidence; the real durable worker canary must be
re-run after deploying the new guarded Backend/worker/observer versions.

The failed canary's entire temporary tenant, Postgres jobs, attempts and scoped
records were deleted, and the worker scaled back to zero; other services stayed
healthy and no external provider credits were consumed.

The source change must pass normal GitHub CI, strict branch-source proof and
safe service-only canary before reopening admission. Physical separate-host
disaster recovery remains Owner-deferred until after launch; full authenticated
5,000-user/15,000 durable job steady-load acceptance, actual 72h natural
stability and FINAL RELEASED VERIFIED remain separate unaccepted gates.

## Python 3.12 Core Owner native security test fixtures (no restore test)

The protected-main CI contract run under Python 3.12 reported 13 preexisting
native mapper test failures: four test fixtures were globally replacing
os.fstat to return partial SimpleNamespace objects even for unrelated
pytest/contextlib temporary file descriptors. Python 3.12 cleanup expects
real stat fields including st_size on those unrelated descriptors.

The correction now forges fstat only for each explicit synthetic loop FD
(10, 33 or 55), delegating all unrelated file descriptors to the genuine
os.fstat. All original security assertions are retained. There are no
production encryption/mount code changes and no FR06 physical cold-host
recovery or final-release acceptance claim. The 14 directly affected native
security tests passed locally; GitHub Python 3.12 remains authoritative.

## Isolated real DB/Redis verification after CI fixture adjustments

After the GitHub backend test stopped at the old Gemma-only Free resolver
fixture, the fixture was updated to the reviewed Qwen model without weakening
tenant boundaries. Isolated PostgreSQL/Redis testing confirmed the corrected
durable resolver and route policy.

A second real isolated PostgreSQL+Redis suite checked 18 cases across model
refresh, Free/Paid and tenant policy, and the Project AI live provider adapter.
It initially exposed an outdated model-refresh service file in the old
Backend image: that image still considered configured/disconnected legacy
Ollama records in the single-provider count. The protected main source
already fixes this and the corrected test image included that exact source
SHA-256. All 18 tests then passed. Production Backend/worker release images
must explicitly include the current main model-refresh module rather than
inheriting stale source from a base image.

An additional isolated Qwen compact-coder suite passed 26 contract tests,
including the exact 640-token limit and original policy-task budget.
The tests use synthetic data only; no expensive provider was invoked.

## SHA256 evidence

- failed production synthetic canary and cleanup: b084816caf3537e374a2e22fd9e895b3b46b003d2a1bb91802d7a4094f542c5c
- real bounded planner result: 0934cb624cff9306e27237114275e91b212446a4e0b4f534b67829fc0197889d
- real four-role and compiled app: 9f3578ac0c0bec05659c46ec824769e62c728c270af4358e061452a3ac98d5f4
- offline 25 tests: e0da41918e54216729fa2395631ed9ef63fe8c1618166bcd0d7334159d751f58

Isolated current-model refreshed provider suite SHA-256: ae9fef2bb9005b8454e3358e435b0999b44c1b8156d0f831c210b0386cd44977
Isolated bounded local coder suite SHA-256: d56270a5254e842f518f14195efa997a0788df78a897c9ba3df656321d80ca98
