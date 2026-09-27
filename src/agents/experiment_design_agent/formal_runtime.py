"""Resource and I/O boundaries for mathematical worker processes."""

import os
from pathlib import Path
import sys


_JOB = None


def limit_resources(memory_mb=1536):
    memory_bytes = int(memory_mb) * 1024 * 1024
    if os.name != "nt":
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        return
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class Counters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", Counters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    job = kernel.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x100 | 0x200 | 0x8 | 0x2000
    limits.BasicLimitInformation.ActiveProcessLimit = 1
    limits.ProcessMemoryLimit = memory_bytes
    limits.JobMemoryLimit = memory_bytes
    if not job or not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        raise OSError(ctypes.get_last_error(), "Cannot apply mathematical worker resource limits")
    global _JOB
    _JOB = job


def restrict_io():
    readable = {Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()}
    for name in ("sympy", "z3", "mpmath"):
        module = sys.modules.get(name)
        if module is not None and getattr(module, "__file__", None):
            readable.add(Path(module.__file__).resolve().parent)
    scratch = Path.cwd().resolve()
    sys.dont_write_bytecode = True

    def audit(event, args):
        if event.startswith(("socket.", "subprocess.", "ctypes.")) or event in {
            "os.system", "os.fork", "os.forkpty", "os.posix_spawn", "os.exec", "os.spawn", "os.startfile",
            "os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.link", "os.symlink", "os.chmod", "os.chdir",
        }:
            raise PermissionError(f"mathematical_worker_io_denied:{event}")
        if event == "open" and not isinstance(args[0], int):
            path = Path(os.fsdecode(args[0])).resolve()
            mode = args[1] if len(args) > 1 else "r"
            flags = args[2] if len(args) > 2 else 0
            writing = isinstance(mode, str) and any(flag in mode for flag in "wax+")
            writing = writing or isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            if writing or not (path.is_relative_to(scratch) or any(path.is_relative_to(root) for root in readable)):
                raise PermissionError("mathematical_worker_file_access_denied")
    sys.addaudithook(audit)


def prepare_runtime(task):
    if task.get("backend") not in {"sympy", "z3", "numerical"}:
        return
    limit_resources(task.get("memory_limit_mb", 1536))
    __import__("sympy")
    if task.get("backend") == "z3":
        __import__("z3")
    restrict_io()
