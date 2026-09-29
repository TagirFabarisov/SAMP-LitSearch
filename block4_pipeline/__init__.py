"""Block-4 systematic-search pipeline for SAMP RQ4.2.

Executes the frozen search protocol (Block 4A, revision 3) against scholarly sources,
preserves raw evidence, normalizes records, separates retrieval hits from unique
documents, and reports status. It contains no language-model call and makes no
screening decision.
"""

PACKAGE_ROOT = __path__[0]
