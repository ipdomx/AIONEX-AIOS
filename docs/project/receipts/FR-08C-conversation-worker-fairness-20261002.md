# FR-08C conversation worker fairness

Owner interactive takeover implementation.

- Queue scan is bounded at 100 queued governed-conversation jobs.
- Owner priority remains strict across priority classes.
- Jobs at the same priority are selected round-robin by organization + requesting user.
- One conversation is selected at most once per dispatch wave.
- Up to 8 selected jobs are dispatched concurrently.
- run_turn remains the durable claim/no-replay authority; queued/running reconciliation semantics are unchanged.
- 401/403/404 admission failures cancel only the affected unstarted job.
- Worker stop/cancellation still retains uncertain running provider work instead of replaying it.
- No provider, billing, production, deployment or live-service effect is part of this source acceptance.
