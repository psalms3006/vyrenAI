"""Memory package.

Re-exports the durable ``MemoryStore`` implementation so legacy imports like
``from memory import MemoryStore`` keep working after the ``memory`` directory
was added for the Obsidian adapter.
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent.parent / "memory.py"
_Spec = spec_from_file_location("_memory_impl", _MODULE_PATH)
_impl = module_from_spec(_Spec)
_Spec.loader.exec_module(_impl)

MemoryStore = _impl.MemoryStore

__all__ = ["MemoryStore"]
