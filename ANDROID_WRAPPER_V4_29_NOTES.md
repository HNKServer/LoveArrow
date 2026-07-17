# Android Wrapper v4.29

CN/honoka compatibility fix: do not run NPPS4 vanilla tutorial state machine for CN clients.

Changes:
- After CN starter unit selection, mark `tutorial_state = -1` instead of leaving the account in NPPS4 tutorial phase 1.
- CN `/tutorial/progress` and `/tutorial/skip` now become tolerant no-op finalizers.
- CN login/userInfo auto-finalizes existing accounts which already have active starter units but are stuck in tutorial state 0/1/2/3 from older test builds.
- GL/JP behavior is unchanged.

Rationale:
- honoka-chan creates/uses already-initialized accounts and does not depend on NPPS4's JP tutorial phase sequence.
- The CN 9.7.x client can enter native crash loops when the server leaves it in a half-NPPS4, half-CN tutorial state.

Additional CN lbonus compatibility:
- CN clients can call `/main.php/lbonus/execute` after tutorial skip without the JP/GL X-Message-Code contract.
- In CN compat mode only, `/lbonus/execute` bypasses XMC verification while keeping the authenticated user context.
- This prevents the first home transition from looping on HTTP 422 connection errors.
