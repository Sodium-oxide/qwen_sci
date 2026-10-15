"""Capabilities are registered by the host, not invented by planning responses."""

from .backends.mathir_backend import MathIRBackend
from .backends.pyscf_backend import PySCFBackend
from .backends.python_project_backend import PythonProjectBackend

BACKENDS = {backend.backend_id: backend for backend in (MathIRBackend(), PySCFBackend(), PythonProjectBackend())}


def get_backend(backend_id: str):
    if backend_id not in BACKENDS:
        raise ValueError(f"unknown_backend:{backend_id}")
    return BACKENDS[backend_id]
