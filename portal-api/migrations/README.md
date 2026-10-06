# Database migrations

- **A new install** starts from `../baseline/000_baseline.sql` (the whole schema as of migration 040), then applies any
  migration newer than 040 from this folder, each followed by `019_restrict_public_functions.sql` (the rights check).
  See `docs/SETUP-STEPS.md`, step 4.
- **A running system** applies only the new numbered files of an update, in order (the updater does it; by hand see
  `docs/README-start-here.md`, "Deploy"). Back up first. Every migration has a `_rollback.sql` partner.
- **`019_restrict_public_functions.sql`** stays here: the updater and every deploy run it after each migration.
- **`history/`** holds migrations 010 to 040 and their rollbacks, the story of how the database got here. They cannot be
  replayed on an empty database (the first tables came from an older system) and a running system has applied them all.
  Some old tests (`../tests/*_db.py`) replay one of them on a copy of the database as it was *before* that migration.
- **The next number is 046.** Put a new migration directly in this folder: `046_<name>.sql` and `046_<name>_rollback.sql`.
  The updater only picks up files named `NNN_name.sql` here, never the ones in `history/`.
- After a change to the schema, run `../baseline/check-baseline.ps1` to see that the baseline still matches (rebuild the
  baseline when a migration should become part of a fresh install: the header of the baseline says how it was made).
