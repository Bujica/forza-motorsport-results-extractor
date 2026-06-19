Alembic migrations for the SQLite persistence layer live here.

`0001_db_vnext_baseline` executes the frozen
`versions/0001_db_vnext_schema.sql` contract. It must not import current
SQLModel metadata or call `create_all()`.

Normal CLI/GUI runtime opens only a current schema. It never creates tables or
auto-upgrades the database. Use the explicit maintenance flow:

```text
python -m forza maintenance db-reset --yes
python -m forza maintenance db-upgrade
python -m forza maintenance db-doctor
```

Future schema changes require a new Alembic revision. Keep migrations
reproducible from an empty database and independent from later model changes.
