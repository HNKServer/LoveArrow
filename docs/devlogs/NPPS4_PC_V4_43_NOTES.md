# v4.43 — CN + GL CDN overlay

This revision keeps the CN 97.4.6 archive authoritative and adds a narrow online fallback for missing extracted files.

- `/cn-extracted/Android/...` first serves the configured CN extracted directory.
- If the file is absent, NPPS4 asks the configured NPPS4-DLAPI `api/v1/getfile` endpoint for that single GL asset, verifies size/MD5/SHA256, stores it in `data/gl_overlay_cache`, then serves the local cached copy.
- `download/getUrl` now reports the upstream size for missing files so the client does not discard the request as zero-length.
- Exact path is preferred; `en/` and non-`en/` variants are tried only as a compatibility fallback.
- CN application/content versions, update ZIPs, server_info, package IDs and server-side master databases are not switched to GL.

This directly addresses the secretbox 404s shown in log29. A complete Memories Gallery still needs a client-side GL museum master/content overlay; the included toolkit can mirror the Android archive and inspect it, but v4.43 does not inject an unverified GL database into the CN client.
