"""Deprecated bootstrap entry point.

Creates only an explicitly configured master using the secure bootstrap flow.
There are no default users, static passwords, printed secrets or schema changes.
"""
from scripts.create_master import main

if __name__ == "__main__":
    main()
