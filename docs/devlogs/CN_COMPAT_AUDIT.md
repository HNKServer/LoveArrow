# CN / honoka compatibility audit

This document records the compatibility decisions for the CN client in the NPPS4
branch.  The goal is not "least lines of code".  The goal is:

1. keep NPPS4's existing GL/JP behavior intact unless a shared change is safe;
2. route CN client protocol differences through explicit adapters;
3. reuse NPPS4 core gameplay/state wherever possible;
4. copy honoka-chan behavior only where it is necessary for the CN client state
   machine to work.

## Confirmed NPPS4 assumptions which are dangerous for CN

| Area | NPPS4 original assumption | CN / honoka-compatible rule |
|---|---|---|
| Version parsing | `major.minor` SIF server version is enough | APK `Client-Version`, package version `97.4.6`, and `99_0_*` update order are separate concepts |
| Dynamic server info | Append JP/GL `/server_info/{hash}` encrypted as `config/server_info.json` | CN uses a honoka-shaped `99_0_115.zip` override and must not receive the JP/GL dynamic server-info package |
| Update package structure | A synthetic tiny ZIP can be enough | Use a real CN `99_0_*` template shape and replace the server-info entry only |
| `/download/event` request model | Batch-shaped request model is acceptable | honoka ignores the request; accept any CN body and return empty list |
| `/download/batch` version gate | Return files as long as backend can find them | honoka returns data only when `client_version == PackageVersion` |
| `package_list` shape | `list[int]` | CN may send objects; adapters must accept them without leaking random dicts into NPPS4 core |
| GHome endpoints | 200/empty stubs are harmless | Some SDK responses control login/account state and must be bridged to NPPS4 users |
| Empty successful response | HTTP 200 means success | CN native code may assert on empty lists in the wrong state, such as `download list is empty !` |

## Current hard rules

- `cn_archive` must be treated as a CN profile, not as a normal NPPS4 download backend with a different file path.
- `send_patched_server_info` must not cause JP/GL-style dynamic server-info injection for CN.
- If a CN route needs honoka behavior for protocol state, implement a CN adapter and then call NPPS4 core state where possible.
- `cn_optional_stubs` are only for log discovery.  A flow passing with stubs enabled is not correctness proof.

## Download flow reference

Expected CN flow:

```text
first launch
→ /download/update returns 99_0_* small update packages and 99_0_115 override when needed
→ client restarts or re-enters
→ /download/update returns empty only after the client is genuinely at PackageVersion
→ /download/batch and /download/additional drive the basic/full data selection
→ /download/getUrl serves on-demand extracted files
```

Do not collapse this into a single `/download/update` mega-list unless a real CN
capture proves the client asks for that.  The earlier one-pass experiment broke
the state machine.

## Diagnostic endpoint

When the server is running, open:

```text
/npps4/cn-compat-audit.json
```

It reports:

- active region and download backend;
- whether CN optional stubs are enabled;
- CN archive preflight warnings;
- whether the generated override ZIP contains root `server_info.json` and/or old
  `config/server_info.json`;
- route-by-route adapter expectations.

## v4.26 confirmed issue: stale/prod CN server_info

Logcat showed that after the small initial 99_0_* update stage, GHome calls still
used `127.0.0.1:8080`, but the native game layer connected to
`prod.game1.ll.sdo.com:80`. This means the override package must not be a static
prebuilt ZIP. It must decrypt the real CN template `server_info.json`, patch all
private-server endpoints to the actual request host, and re-encrypt it using CN
HonokaMiku/Honky-compatible encryption.

## v4.27 additional guard

v4.26 still allowed the CN client to reach `prod.game1.ll.sdo.com` after the
initial 99 update stage. v4.27 therefore no longer relies only on a final
`99_0_115.zip` override. In `cn_archive` mode it dynamically patches every served
`99_0_*.zip` which contains `server_info.json` or `config/server_info.json`.
This is intentionally limited to the CN update-package stage and does not change
NPPS4's GL/JP download backends.
