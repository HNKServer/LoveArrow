# NPPS4 DLAPI mirror helper

This folder contains `fetch_npps4_dlapi_archive.py`, a stdlib-only downloader that mirrors an NPPS4-DLAPI source into NPPS4's `internal` archive directory layout.

Typical usage:

```bash
python fetch_npps4_dlapi_archive.py \
  --server https://ll.sif.moe/npps4_dlapi \
  --out D:/sif_gl_archive \
  --platforms Android \
  --workers 8
```

Then configure NPPS4:

```toml
[download]
backend = "internal"

[download.internal]
archive_root = "D:/sif_gl_archive"
```

For a first quick check without downloading all binaries:

```bash
python fetch_npps4_dlapi_archive.py --metadata-only --out D:/sif_gl_archive_meta
```

The script writes:

- `generation.json`
- `release_info.json`
- `<Platform>/update/infov2.json`
- `<Platform>/package/<version>/<package_type>/info.json`
- `<Platform>/package/<version>/<package_type>/<package_id>/infov2.json`
- NPPS4 DB files under `<Platform>/package/<version>/db/*.db_`

It resumes downloads when files already exist and pass size/hash checks.
