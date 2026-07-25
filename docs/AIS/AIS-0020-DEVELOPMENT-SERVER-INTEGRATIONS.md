# AIS-0020 — Development & Server Integrations

Phase 8 Part 2 extends the Infrastructure Core with contract-based SSH, Git, GitHub, GitLab and Docker providers.
All external effects are delegated to injected asynchronous runners. Default runners are deterministic dry runners, allowing the core to remain dependency-free and testable.

Security invariants:

1. Secrets remain resolved by the Phase 8 credential and vault services.
2. Dangerous shell commands are blocked before runner invocation.
3. Destructive operations require explicit approval.
4. Providers expose normalized health and execution results.
5. Remote jobs have explicit states and cancellable tasks.
