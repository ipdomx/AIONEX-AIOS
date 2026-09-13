# 36N / FR-04C3 Redis recovery contract

FR-04C3 locks the Redis DR contract as docs/tests only: Redis remains AOF/noeviction for runtime restarts, but `redis_data` is excluded from cross-environment asset snapshots. Restored environments must start Redis empty or flush runtime namespaces and rebuild volatile coordination state from PostgreSQL/assets/providers.
