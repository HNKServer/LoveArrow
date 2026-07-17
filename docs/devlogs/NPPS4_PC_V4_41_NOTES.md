# NPPS4 PC v4.41 — CN Live, original announcement and content-access merge

The PC source contains the same server changes as Android Wrapper v4.41. The
implementation remains NPPS4-first: original NPPS4 gameplay and achievement
systems are preserved, while CN compatibility is added at the narrowest proven
boundaries.

## Main changes

1. Restore NPPS4's intentional Swagger/API documentation announcement at
   `/main.php/api`, including the login WebView and home type-2 banner link.
2. Use the CN archive's unprefixed WebView poster path for CN 9.7.1 while
   retaining upstream language paths for other clients.
3. Allow only authenticated CN CROSS-XMC endpoints to proceed after successful
   token validation, so `/live/play` reaches NPPS4's real implementation.
   SHARED XMC and non-CN behaviour are unchanged.
4. Bundle the exact CN 9.7.1 client master overlay instead of relying on reduced
   honoka-shaped tables.
5. Apply a versioned, idempotent post-service content migration through
   NPPS4's real achievement/reward pipeline.
6. Add actual per-user archive state and endpoints for event and multi-unit
   stories; replay does not duplicate historical rewards.

Normal main-story, bond, rank, card and Live-clear progression is not forcibly
completed. See `ANDROID_WRAPPER_V4_41_NOTES.md` for the full implementation and
validation record.
