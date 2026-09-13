# 36N / FR-04C4 DB-assets retention contract

FR-04C4 records the DB/assets consistency and retention/delete contract as docs/tests only. Platform backups require durable companion asset snapshot evidence; restore validation validates the snapshot against stored evidence; retention deletes the DB dump and companion snapshot as one logical unit while retaining audit/checksum evidence.
