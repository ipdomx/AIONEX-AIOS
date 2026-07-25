# AIS-0001: Module Boundaries

1. A module owns its implementation and persistent data.
2. Cross-module communication uses public contracts, commands, or events only.
3. Contracts are immutable after publication; breaking changes require a new version.
4. Every event carries tenant, source, version, and correlation identity.
5. No module may silently write into another module's directory.
