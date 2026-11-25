"""Controllers of the window: plain Python, no Qt and no Tk.

Each controller gets what it needs by injection (`submit` of a lane, a clock, a single-shot `timer(ms, fn)`, a
sink or observers), so it is tested with stand-ins. View-models (later) turn their snapshots into Qt types.
"""
