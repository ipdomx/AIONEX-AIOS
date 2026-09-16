# FR-06C5D guarded host-state cutover

The live executor pre-copies into the encrypted host-state vault, stops the exact application topology and Docker, seals every legacy source read-only, performs an exact final-delta copy, then activates encrypted binds and restarts the exact planned container IDs. Blind rollback is forbidden after candidate containers start because host/operator state may diverge immediately.
