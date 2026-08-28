"""Google Workspace integration — auth, calendar, gmail.

Every module in this package is read-only in the current phase. Any write
scope (compose, calendar events, etc.) must be added deliberately and gated
by the approval layer, not slipped into `SCOPES` in `auth.py`.
"""
