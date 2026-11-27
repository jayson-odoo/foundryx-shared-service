# planner3d S1 module migration on a scratch Postgres

Run in the lane's cloud sandbox on a throwaway Postgres 16 database (`p3_s1_scratch`), never a shared one.

1. `alembic upgrade head` (core), then `run_module_migrations(engine, "planner3d")`: state `fresh` -> `versioned`,
   version `0002_planner3d_s1_gateway`, tables `p3_api_audit, p3_api_key, p3_delivery, p3_job, p3_job_file,
   p3_receiver, p3_upload` (+ the version table).
2. Existing-DB path: `alembic downgrade 0001_planner3d_baseline` (the S3 shape: `p3_job` without the three new
   columns, only `p3_job` + `p3_job_file`), insert one old `p3_job` row, then `run_module_migrations` again:
   version `0002_planner3d_s1_gateway`, columns `api_key_id, idempotency_ref, request_hash` added, the old row is
   kept (`idempotency_ref` NULL), `uq_p3_job_idempotency (tenant_id, idempotency_ref)` created. A second run is a no-op.
3. `migration.sql` (this folder, the crew-migration SQL) applied twice on the S3 shape: no error, 8 tables; the module
   migration run afterwards moves the version to `0002_planner3d_s1_gateway` with no error (every statement is
   `IF NOT EXISTS` / `checkfirst`).
