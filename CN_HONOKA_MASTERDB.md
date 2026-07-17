# CN honoka master DB integration

This build embeds `npps4/assets/honoka_main.db`, copied from honoka-chan's `assets/main.db`.

NPPS4 still has two distinct DB concepts:

- **Server account/progress DB**: `data/main.sqlite3`, created and migrated by NPPS4/Alembic. This stores accounts, units owned by users, decks, friends, greetings, rewards, etc.
- **Read-only master data**: songs, units, scenarios, achievements, accessories, download metadata, etc. Original NPPS4 expects split DB files such as `game_mater.db_`, `unit.db_`, `live.db_`, `item.db_`, etc.

This build no longer treats CN CDN ZIP files as the default source of master DBs. The CDN ZIPs remain read-only client download files. Instead, the `cn_archive` backend resolves master DBs in this order:

1. `[download.cn_archive].db_root`, if it already contains split DB files.
2. A generated server-side split DB set under `data/db_cn_honoka`, created from the embedded `npps4/assets/honoka_main.db`.

The generator is conservative. It creates NPPS4's declared SQLAlchemy schema, copies rows from honoka tables with matching names and columns, and leaves unavailable NPPS4-only tables empty. This is intended as a runnable CN baseline and a bridge for further conversion work, not as a claim that honoka `main.db` perfectly matches all NPPS4/Global master data tables.

Manual generation:

```bash
python -m npps4.tools.cn_honoka_master --out data/db_cn_honoka --overwrite
```

The generated DBs include a `_npps4_cn_honoka_manifest` table describing which honoka tables were copied.
