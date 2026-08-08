# Phase 34B — RunPod Production Endpoint & Cost-Control Acceptance

Status: **accepted**

## Production endpoint contract

- Dedicated endpoint name: `aionex-hunyuan3d-production`.
- Endpoint identifier is not committed; it is stored only as `RUNPOD_ENDPOINT_ID` in protected production `RUNPOD_GPU.env` (`0600`).
- Template: `1e0hug1c4t`.
- Image: `ipdomx/aionex-hunyuan3d:phase33-lazy2`.
- Active workers / minimum workers: `0`.
- Maximum workers: `1`.
- GPUs per worker: `1`.
- Idle timeout: `5s`.
- Execution timeout: `1800s`.
- Initialization timeout: `RUNPOD_INIT_TIMEOUT=1800`.
- Container command/entrypoint override: none.

## Live acceptance evidence

A real production-endpoint request generated a binary GLB from the Hunyuan3D demo image.

- Status: `COMPLETED`.
- Provider queue delay: `10.176s`.
- Provider execution time: `103.352s`.
- Artifact size: `12,274,660 bytes`.
- Binary header validation: `glTF` magic passed.
- Queue after completion: `0` queued / `0` in progress.
- Automatic compute scale-down was observed without deleting the endpoint: `running=0`.
- FlashBoot retained an `idle/ready` cached worker state. RunPod documents idle Flash workers as non-billed and documents `workersMin=0` as the scale-to-zero configuration. This cached state is therefore accepted only while compute remains `running=0`; any future billed idle compute is a release blocker.
- Live cancellation returned `CANCELLED` and live queue purge returned `completed`, with no queued job left behind.

Primary operational references:
- RunPod endpoint settings: https://docs.runpod.io/serverless/endpoints/endpoint-configurations
- RunPod Serverless pricing: https://docs.runpod.io/serverless/pricing
- RunPod worker lifecycle: https://docs.runpod.io/flash/execution-model

## Recovery and cost boundaries

`RunPodServerlessClient` and `HunyuanServerlessController` now expose and test:

- async submission and status polling;
- cancellation;
- queue purge;
- queue-stall detection;
- bounded retry;
- runtime cancellation and cleanup;
- per-job estimated-cost ceiling;
- daily spend ceiling;
- monthly spend ceiling;
- configurable owner warning threshold;
- owner alert events for warnings, blocks, retries, provider failures and stuck-job recovery.

## Owner-controlled user access

3D is **not a general-user feature**. Default policy permits only the highest current public plan, `business`, and requires entitlement `3d.generation`.

The Super Owner controls the complete policy from `/owner/3d`, including:

- enable/suspend 3D globally;
- eligible plan codes;
- required entitlement;
- explicit user allow list;
- explicit user deny list;
- per-user concurrency;
- runtime and queue limits;
- retry count;
- per-job, daily and monthly GPU spend ceilings;
- owner alert threshold.

The default `business` portal plan carries `3d.generation`; lower plans do not. Explicit owner deny always wins over plan/entitlement access, while an explicit owner allow can override plan eligibility.

## Isolation rule

Phase 34B was implemented in its own Git worktree/branch. No unrelated parallel-conversation changes are imported or modified by this batch.
