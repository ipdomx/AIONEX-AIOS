# Phase 22B — Local Model Sandbox

## Scope

Phase 22B validates one real local model against the existing six-department `EngineeringOrganization` without adding a cloud provider, API key, production dependency, or production deployment path.

The implementation reuses the existing `OllamaProvider`. It adds a strict loopback-only HTTP transport and a sandbox executor that writes only to an explicit absolute output root.

## Validated server profile

- Architecture: `x86_64`
- CPU: Intel Xeon E-2236, 6 physical cores / 12 threads, AVX2
- RAM: 62 GiB total, about 59 GiB available before the experiment
- Disk: about 779 GiB available before acquisition
- Accelerator: CPU-only; no supported NVIDIA GPU
- Docker Engine: 29.1.3
- Docker Compose: 2.40.3

## Acquired runtime

- Image: `ollama/ollama`
- Pinned image digest: `ollama/ollama@sha256:4dea9fb511947e24a84237bb636b0203abcb2ff0d3fbc7b4ff865deb91362131`
- Ollama version in the image: 0.32.5
- Model: `qwen3:8b`
- Model digest: `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`
- Model size reported by Ollama: 5,225,388,164 bytes
- Quantization: Q4_K_M
- Retained model volume: `aionex-ollama-phase22b-models`

Model acquisition used an isolated acquisition container and network. Those temporary resources were deleted after the model was verified. The image and model volume were retained as requested.

## Runtime isolation

The experiment used:

- Runtime container: `aionex-ollama-phase22b`
- Execution network: `aionex-ollama-phase22b-internal`
- Docker network property: `Internal=true`
- Production-network membership: none
- CPU limit: 4 CPUs
- Memory limit: 12 GiB
- Memory plus swap limit: 12 GiB
- Parallel requests: 1
- Loaded models: 1
- Context: 4096
- Temperature: 0
- Fixed seed: 22
- PID limit: 512
- Restart policy: no
- Linux capabilities: all dropped
- `no-new-privileges`: enabled
- `OLLAMA_NO_CLOUD=1`

The internal Docker network intentionally had no default route. Docker did not activate a published host port for the internal-only network on this engine. A temporary standard-library TCP relay therefore bound only `127.0.0.1:11435` and forwarded only to the runtime container's internal address and port 11434. The relay was outside the repository, contained no provider credentials, and was removed after the experiment. Port 11435 was confirmed closed during cleanup.

No production Compose file, environment file, service, database, network, or container was changed or restarted.

## Safety proof

The manifest records:

```json
{
  "model_acquisition_network_used": true,
  "execution_network_used": false,
  "network_used": false,
  "provider_keys_used": false,
  "cloud_model_used": false,
  "production_modified": false
}
```

`network_used=false` refers to model inference. Model acquisition is separately and truthfully recorded as having used the network.

## Code contract

`src/aios/local_model_sandbox.py` provides:

- `OllamaLocalHTTPTransport`
  - accepts exactly `http://127.0.0.1:11435`
  - rejects every other scheme, host, port, path, query, or credential form
  - disables proxy use
  - enforces one active request
  - applies bounded timeouts
  - normalizes Ollama timing and token metrics

- `LocalModelSandbox`
  - uses the existing `OllamaProvider`
  - runs Architecture, Backend, Frontend, Security, Quality, and DevOps sequentially
  - allows at most two attempts per department
  - requires strict JSON with exact keys
  - requires one technical-evidence item for every acceptance criterion
  - rejects duplicate, missing, unknown, or empty evidence
  - writes six artifacts plus `manifest.json`, `REPORT.md`, `comparison.json`, and `COMPARISON_REPORT.md`
  - uses atomic writes and a staging directory
  - rejects path traversal and duplicate execution IDs
  - cleans staging after failure
  - executes no shell command and imports no subprocess API

- `CgroupResourceMonitor`
  - reads the already-created runtime cgroup directly
  - records CPU usage, memory, host available memory, host load, and execution phase
  - invokes no Docker or shell command

## Real execution result

Output root:

`/var/tmp/aionex-phase22b/sandbox-output`

Executions:

- Offline mock: `/var/tmp/aionex-phase22b/sandbox-output/offline-mock`
- Local model: `/var/tmp/aionex-phase22b/sandbox-output/local-qwen3-8b`

The local model completed all six departments with one request per department and no retry.

- Strict JSON valid for all departments: yes
- Acceptance coverage: 1.0
- Artifacts: 6
- Prompt tokens: 1,212
- Generated tokens: 3,346
- Aggregate generation rate: 2.5474 tokens/second
- Total wall duration: 1,456.456546 seconds
- Aggregate model load duration: 36.430023 seconds
- Aggregate prompt evaluation duration: 106.247155 seconds
- Aggregate generation duration: 1,313.512485 seconds
- Peak cgroup CPU sample: 414.1511% of one CPU
- Peak cgroup memory: 6,625,099,776 bytes
- Minimum host available memory recorded: 57,645,473,792 bytes
- Maximum one-minute host load recorded: 6.89
- Safety aborts: none
- OOM: none

Department wall times and output tokens:

| Department | Wall seconds | Generated tokens | Tokens/s | Attempts |
|---|---:|---:|---:|---:|
| Architecture | 245.133729 | 564 | 2.5436 | 1 |
| Backend | 221.255704 | 513 | 2.6220 | 1 |
| Frontend | 201.020437 | 454 | 2.5787 | 1 |
| Security | 307.030286 | 721 | 2.5341 | 1 |
| Quality | 255.699656 | 586 | 2.5085 | 1 |
| DevOps | 226.297258 | 508 | 2.5154 | 1 |

## Engineering review

The local model truthfully returned `tests_passed=false` and `security_reviewed=false`; it was instructed not to fabricate execution evidence. Consequently:

- Approved: false
- Readiness score: 0.82

Blocking findings:

- Architecture: tests have not passed
- Backend: tests have not passed
- Backend: security review is missing
- Frontend: tests have not passed
- Security: tests have not passed
- Security: security review is missing
- Quality: tests have not passed
- DevOps: tests have not passed
- DevOps: security review is missing

The rework plan requires the department test plans for all six departments and security review for Backend, Security, and DevOps.

This is the expected truthful distinction between generated engineering analysis and executed verification. The sandbox does not convert generated prose into false test evidence.

## Offline mock comparison

Both modes created six valid JSON artifacts with full acceptance-criterion coverage.

The deterministic structural quality heuristic produced:

- Offline mock quality score: 0.5361
- Local model quality score: 0.9415
- Quality delta: +0.4054 for the local model
- Offline pairwise repetition: 0.7832
- Local-model pairwise repetition: 0.2339

The heuristic measures schema validity, acceptance coverage, department-specific terminology, actionable implementation steps, clear risk/mitigation pairs, technical-evidence density, and cross-department repetition. It is a transparent structural comparison, not a human review substitute.

The Offline Mock result was approved at readiness 1.0 because it deterministically marks its synthetic test and security gates as complete. The real local-model result was not approved and scored 0.82 because it did not claim tests or security reviews that were not actually executed.

## Test validation

The required isolated suite passed:

- 60 passed for the Phase 22B sandbox, Offline Mock Executor, Engineering Organization, and core provider implementation tests.

The broader related provider and routing suite also passed:

- 68 passed, including AI routing and final provider integration.

A best-effort repository-wide `pytest` collection was also attempted. It could not collect 26 unrelated historical test modules because their packages are absent from the current repository tree, including old iOS, payments, meetings, self-evolution, release-candidate, and plugin modules. These are pre-existing repository-wide collection gaps and are not imports or failures introduced by Phase 22B. No unrelated module was modified to conceal or bypass those errors.

## Cleanup result

After the experiment:

- Runtime container removed
- Internal execution network removed
- Acquisition container removed
- Acquisition network removed
- Temporary loopback relay stopped and removed from operation
- Port 11435 confirmed closed
- Model volume retained
- Pinned Ollama image retained
- Docker cache not cleaned
- Production services not restarted
- Production containers remained healthy/running

The experiment outputs and model are not repository content and must not be added to Git.
