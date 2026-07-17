# Pydantic / Chaquopy note

This Android wrapper uses Chaquopy.  NPPS4 upstream is written for Pydantic v2,
but Pydantic v2 depends on `pydantic-core`, a Rust native extension.  At the
time this wrapper was prepared, Chaquopy's Android package repository did not
provide a compatible `pydantic-core` wheel, so Gradle failed during
`:app:installDebugPythonRequirements`.

The wrapper therefore pins `fastapi==0.99.1` and `pydantic>=1.10.20,<2`, and
adds `sitecustomize.py` plus `pydantic_settings.py` to provide the small subset
of Pydantic v2 APIs used by NPPS4.  This is a packaging workaround only; the
server code and CN compatibility logic remain the NPPS4 v10 code path.

If Chaquopy later ships `pydantic-core` Android wheels, this compatibility shim
can be removed and the requirements can return to Pydantic v2.
