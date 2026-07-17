# NPPS4-first compatibility policy

This tree uses NPPS4 as the authoritative implementation and honoka-chan only as a protocol/client-compatibility reference.

Rules applied from v4.37 onward:

1. Do not replace a working NPPS4 implementation with a smaller hard-coded or empty response merely because honoka-chan returns that shape.
2. Prefer additive compatibility: preserve NPPS4 fields and add fields required by the CN client.
3. If a feature is genuinely unsupported by an older client, gate only that feature by client capability/version; do not replace the whole endpoint.
4. Keep CN-specific behavior behind CN compatibility checks wherever practical, so JP/GL/desktop behavior remains NPPS4-native.
5. A honoka-chan implementation may be adopted when it is more complete or correct, but only after comparing state handling, persistence, validation and side effects—not by copying response literals blindly.
6. Diagnostic logging must not mutate game state or response data.
7. Friend interoperability remains a tracked follow-up.  Existing NPPS4 friend behavior must be preserved; the placeholder cross-server layer will be implemented only after the core CN login/tutorial/home path is stable.
