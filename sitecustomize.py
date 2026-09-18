"""Diagnostic-only startup hook for the disposable 013B qualification child."""

import os


TRACE_ROOT = os.environ.get("MH_QUALIFICATION_DIAGNOSTIC_ROOT")
argus_trace = None
ARGUS_DIAGNOSTIC_BUILD_ID = "ARGUS_019M_DIAGNOSTIC_V1"

if TRACE_ROOT:
    try:
        import faulthandler
        import time

        if not os.path.isabs(TRACE_ROOT):
            raise ValueError("Diagnostic root must be absolute")
        _trace_fd = os.open(
            os.path.join(TRACE_ROOT, "python-stages.log"),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        _stack_file = open(
            os.path.join(TRACE_ROOT, "python-stacks.log"),
            "x",
            encoding="ascii",
            buffering=1,
        )

        def argus_trace(stage):
            if not stage or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for ch in stage):
                raise ValueError("Invalid diagnostic stage")
            row = f"{time.time_ns()}|{os.getpid()}|{stage}\n".encode("ascii")
            if os.write(_trace_fd, row) != len(row):
                raise OSError("Short diagnostic stage write")
            os.fsync(_trace_fd)

        argus_trace("H2_PYTHON_RUNTIME_STARTED")
        argus_trace("PYTHON_STARTUP_HOOK_ARMED")
        faulthandler.enable(file=_stack_file, all_threads=True)
        faulthandler.dump_traceback_later(20, repeat=False, file=_stack_file)
        argus_trace("H3_DIAGNOSTIC_BOOTSTRAP_ACTIVE")
    except BaseException as exc:
        try:
            os.write(2, ("DIAGNOSTIC_BOOTSTRAP_FAILED:" + type(exc).__name__ + "\n").encode("ascii"))
        finally:
            os._exit(86)
