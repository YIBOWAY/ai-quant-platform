"""Shared test support package.

Keeping ``tests`` importable lets integration tests reuse narrowly scoped
fixture helpers without relying on pytest's import-mode or the current
working directory.
"""
