"""Opt-in CN safety-net stubs.

Only keep handlers here when they are deliberately no-op fallbacks.  Real CN
compatibility should live in normal game modules, cn_wrappers.py, or system/*.

As of v10 the previously stubbed reward/sellUnit and live/continue paths have
real state-backed implementations, so this module intentionally contains no
registered handlers by default.
"""
