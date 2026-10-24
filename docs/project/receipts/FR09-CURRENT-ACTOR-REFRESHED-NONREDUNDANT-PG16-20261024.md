# FR09 - governed conversations: two live authentication SQL statements

Protected source base: ec9724ec3a7052cea3b1580cad2150cb97e97dea

## Verified improvement

conversation_governance.current_actor() performed redundant live queries to
User, Organization and Role, followed by AuthService.get_user_by_id()
which queried the same joined relations and current permissions again.

The new optional refresh_cached keyword on AuthService.get_user_by_id uses
SQLAlchemy populate_existing=True for all three joined ORM records in
a single fresh SQL query; the second query checks effective live role
permissions. This keyword defaults to False for existing non-governance
calls, preserving their behavior. Governed read-only actor admission
needs exactly two SELECTs against actual PostgreSQL 16. Governed write
admission continues to acquire a live User SELECT FOR UPDATE and needs
exactly three SELECTs.

A naive optimization without populate_existing was rejected after four
official owner-policy authority tests proved that stale SQLAlchemy identity-map
User can conceal a concurrent auth-version revocation. The final
candidate rejects stale user, role and organization versions, checks
live permissions, and preserves request and Owner governance.

## Non-production verification

- 18 auth unit/permission-revocation tests passed without network.
- 39 full real-PostgreSQL governed-conversation integration tests passed.
- 2 real-PostgreSQL SQL budget/locking tests passed.
- 4 real-PostgreSQL Owner authority refresh tests passed, including policy
  update, reset, directory and conversation access revocation.
- Final suite: 63 PASS on a disposable network-none PostgreSQL16 database
  in the independently encrypted FR09 Docker lab.
- The database and test containers were removed; no production DB connection,
  provider call, customer data or worker mutation occurred.

The source change does NOT imply that FR09 has met sustained 5000 active
authenticated users with 15000 conversations and 15000 durable jobs.
No live production images or services are changed merely by merging this code.

Local evidence:
/mnt/aionex/fr09-isolated-lab-20261011/fr09-governed-current-actor-sql-optimization-20261024/FR09-REAL-PG16-ALL-GOVERNANCE-AND-REVOCATION-SECURITY.log
