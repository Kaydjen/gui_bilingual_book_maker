"""The window's only door to the core, as plain `*_task` functions (no Qt, no Tk).

books   library, series, chapters of a book, export, the reader's reads, open book handles
terms   the term base (Tk `TermsDoc`, data-lane `TermStore`), term scans on a snapshot, the terms frontier
run     job record, run / sample relay, run config
checks  failed blocks, check findings, resolving blocks
quota   today's quota and key states
This package is the import list of the helper process (`novelgui.crunch`): it never imports PySide6.
"""
