"""Child process used by the Phase 36B multi-process admission acceptance."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from app.db.base import SessionLocal, engine
from app.db.models import ProjectExecution
from app.db.redis import close_redis, init_redis
from app.services.project_execution_admission import project_execution_admission_slot


async def _admit(index: int, *, batch: str, start_epoch: float) -> tuple[str, float]:
    delay = start_epoch - time.time()
    if delay > 0:
        await asyncio.sleep(delay)
    started = time.perf_counter()
    execution_id = f"p36be-{batch}-{index}"
    async with project_execution_admission_slot():
        async with SessionLocal() as session:
            session.add(
                ProjectExecution(
                    id=execution_id,
                    organization_id=f"p36bl-{batch}-{index}",
                    workspace_id=f"p36bw-{batch}-{index}",
                    project_id=f"p36bp-{batch}-{index}",
                    requested_by_id=f"p36bu-{batch}-{index}",
                    mode="full",
                    provider="synthetic-fake-provider",
                    status="queued",
                    stage="queued",
                    progress=0,
                    objective="Synthetic Phase 36B distributed durable admission job.",
                    external_processing_confirmed=True,
                    budget_cap_usd=0.05,
                    result_summary={},
                    resource_class="project-build-cpu",
                    priority_rank=200,
                    attempts=0,
                    max_attempts=3,
                )
            )
            await session.commit()
    return execution_id, time.perf_counter() - started


async def main() -> int:
    start = int(sys.argv[1])
    stop = int(sys.argv[2])
    batch = sys.argv[3]
    start_epoch = float(sys.argv[4])
    await init_redis()
    try:
        results = await asyncio.gather(
            *(
                _admit(index, batch=batch, start_epoch=start_epoch)
                for index in range(start, stop)
            )
        )
        print(
            "P36B_CHILD_RESULT="
            + json.dumps(
                {
                    "pid": os.getpid(),
                    "ids": [item[0] for item in results],
                    "latencies": [item[1] for item in results],
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
        return 0
    finally:
        await close_redis()
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
