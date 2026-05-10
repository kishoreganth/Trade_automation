# Legacy SQLite import folder

Drop the OLD app's databases here **before** the very first `docker compose up -d`
on the new server:

```
legacy_data/
  messages.db
  analytics.db
```

What happens on first boot:

1. The `migrate` container runs `alembic upgrade head` to create the schema.
2. It detects `stocks` is empty AND these files exist → runs the one-time
   SQLite → Postgres data import.
3. After data is imported, this step **auto-skips on every future deploy**
   (because `stocks` is no longer empty).

You can safely leave the `.db` files here forever — they will not be re-imported
unless the Postgres volume is wiped.

If you have no SQLite legacy data (fresh install), leave this folder empty.
