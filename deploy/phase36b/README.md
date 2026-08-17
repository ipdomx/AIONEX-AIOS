# Phase 36B — Project Worker Scale Assets

These files are deployment foundations, not evidence that production or a physical multi-host cluster is already active.

## Same-host Docker Compose scale

The live worker has no `container_name`, so replicas can be created explicitly after the protected image/migration gate passes:

```sh
docker compose \
  -f web-dashboard/docker-compose.production.yml \
  -f deploy/phase36b/docker-compose.project-worker-scale.yml \
  --profile ai-execution \
  up -d --scale project-worker=2 project-worker
```

The override enables two processes by default and each process can run two governed executions concurrently. PostgreSQL remains the authority for claims, tenant fairness, lease expiry, fencing generation, retry/dead-letter state and worker heartbeats.

Do not increase replicas/capacity merely because the queue is deep. CPU, memory, provider budgets, browser concurrency and shared evidence storage must be measured first.

## Multi-host Kubernetes template

`kubernetes/project-worker.yaml` is a source-controlled cluster template using stable APIs (`apps/v1`, `policy/v1`, `autoscaling/v2`). It deliberately references an invalid placeholder image and two externally supplied RWX PVCs so it cannot be mistaken for a one-command production activation.

Required external gates before real multi-host activation:

1. Replace the image with an immutable digest from the protected AIONEX build/registry.
2. Supply the `aionex-project-worker-runtime` Secret containing only runtime connection values; do not commit values.
3. Supply the `aionex-project-provider-secret` Secret with `project-openai.env`; do not commit values.
4. Provision `aionex-project-execution-rwx` and `aionex-project-reference-rwx` using storage proven to support `ReadWriteMany` from all worker hosts.
5. Run the Phase 36B migration and protected tests before increasing replicas.
6. Validate queue depth, oldest wait, worker saturation, retry rate and dead-letter count through the Super Owner production-runtime endpoint before and after rollout.
7. Roll back by scaling the worker deployment to the last known-good replica count/image. Do not downgrade the schema while any Phase 36B worker is running.

The current batch proves the PostgreSQL live control-plane and synthetic 1000-tenant admission boundary. Physical-host/RWX performance is an explicit activation gate, not a source-test claim.
