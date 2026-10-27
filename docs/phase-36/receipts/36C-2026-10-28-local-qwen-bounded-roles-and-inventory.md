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

## SHA256 evidence

- failed production synthetic canary and cleanup: b084816caf3537e374a2e22fd9e895b3b46b003d2a1bb91802d7a4094f542c5c
- real bounded planner result: 0934cb624cff9306e27237114275e91b212446a4e0b4f534b67829fc0197889d
- real four-role and compiled app: 9f3578ac0c0bec05659c46ec824769e62c728c270af4358e061452a3ac98d5f4
- offline 25 tests: e0da41918e54216729fa2395631ed9ef63fe8c1618166bcd0d7334159d751f58
