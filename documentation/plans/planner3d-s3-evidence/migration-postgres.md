# planner3d module migration on a scratch Postgres

Run on a throwaway database on the local Postgres 17 (never a shared database). Passwords are not shown.

```bash
createdb -O foundryx foundryx_s3_scratch
cd service_backend
export DATABASE_URL=postgresql://foundryx:<password>@localhost:5432/foundryx_s3_scratch
.venv/bin/python -m alembic upgrade head          # core schema, ends at ss_public_link_base
.venv/bin/python -c "
from sqlalchemy import create_engine
from app.config import settings
from app.module_platform.migrations import run_module_migrations, module_migration_state
e = create_engine(settings.database_url)
print('state before:', module_migration_state(e, 'planner3d'))
run_module_migrations(e, 'planner3d')
print('state after:', module_migration_state(e, 'planner3d'))
"
```

Output:

```
state before: fresh
state after: versioned
```

```
psql "$DATABASE_URL" -c '\dt app_planner3d.*' -c 'select * from app_planner3d.alembic_version_planner3d'

    Schema     |           Name            | Type  |  Owner
---------------+---------------------------+-------+----------
 app_planner3d | alembic_version_planner3d | table | foundryx
 app_planner3d | p3_job                    | table | foundryx
 app_planner3d | p3_job_file               | table | foundryx
(3 rows)

       version_num
-------------------------
 0001_planner3d_baseline
(1 row)
```

`\d app_planner3d.p3_job_file` shows the unique constraint `uq_p3_job_file_name (job_id, direction, name)`,
the index `ix_p3_job_file_job (tenant_id, job_id)` and the foreign key to `p3_job`.

The scratch database was then removed with `dropdb foundryx_s3_scratch`. The seed script
(`scripts.bootstrap_db`) was not used: it is fixed to the shared database name.
