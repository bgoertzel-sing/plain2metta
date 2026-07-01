"""SpecAtom-HS local prototype scaffold.

Small, conservative API for indexing Plain-like source, building validation records,
and projecting only safe reified facts to a PeTTa/MeTTa-like syntax.
"""

from .source_indexer import index_source, index_path
from .validators import validate_document
from .backends.petta import emit_reified_atoms, refuse_executable_skeleton

__all__ = [
    "index_source",
    "index_path",
    "validate_document",
    "emit_reified_atoms",
    "refuse_executable_skeleton",
]
