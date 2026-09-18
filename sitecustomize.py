"""Diagnostic-only startup hook for the disposable 013B qualification child."""

import os


TRACE_ROOT = os.environ.get("MH_QUALIFICATION_DIAGNOSTIC_ROOT")
argus_trace = None
ARGUS_DIAGNOSTIC_BUILD_ID = "ARGUS_019M_DIAGNOSTIC_V2"

if TRACE_ROOT:
    try:
        import faulthandler
        import time

        if not os.path.isabs(TRACE_ROOT):
            raise ValueError("Diagnostic root must be absolute")
        _pipe_name = os.environ.get("MH_QUALIFICATION_DIAGNOSTIC_PIPE")
        if _pipe_name:
            import ctypes
            import msvcrt

            if not _pipe_name.startswith(r"\\.\pipe\MomentumHunter-Qualification-"):
                raise ValueError("Invalid diagnostic pipe identity")
            _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            _create_file = _kernel.CreateFileW
            _create_file.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                     ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                     ctypes.c_void_p]
            _create_file.restype = ctypes.c_void_p
            _handle = _create_file(_pipe_name, 0xC0000000, 0, None, 3, 0, None)
            if _handle == ctypes.c_void_p(-1).value:
                raise OSError(ctypes.get_last_error(), "Diagnostic pipe connection failed")
            _trace_fd = msvcrt.open_osfhandle(_handle, os.O_BINARY | os.O_RDWR)
        else:
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
            if _pipe_name:
                if os.read(_trace_fd, 1) != b"1":
                    raise OSError("Diagnostic parent did not durably acknowledge stage")
            else:
                os.fsync(_trace_fd)

        argus_trace("H2_PYTHON_RUNTIME_STARTED")
        argus_trace("PYTHON_STARTUP_HOOK_ARMED")
        faulthandler.enable(file=_stack_file, all_threads=True)
        faulthandler.dump_traceback_later(20, repeat=False, file=_stack_file)
        argus_trace("H3_DIAGNOSTIC_BOOTSTRAP_ACTIVE")
        if os.environ.get("MH_QUALIFICATION_DIAGNOSTIC_PARENT_ACK") == "REQUIRED" and not _pipe_name:
            _ack_path = os.path.join(TRACE_ROOT, f"parent-attestation-{os.getpid()}.ok")
            _deadline = time.monotonic() + 6
            while time.monotonic() < _deadline:
                try:
                    with open(_ack_path, "r", encoding="ascii") as _ack:
                        if _ack.read(128) == f"ARGUS_019M_PARENT_ATTESTED_V1|{os.getpid()}":
                            argus_trace("PARENT_ATTESTATION_CONFIRMED")
                            break
                except FileNotFoundError:
                    pass
                time.sleep(0.02)
            else:
                argus_trace("DIAGNOSTIC_PARENT_ATTESTATION_TIMEOUT")
                os._exit(87)
    except BaseException as exc:
        try:
            os.write(2, ("DIAGNOSTIC_BOOTSTRAP_FAILED:" + type(exc).__name__ + "\n").encode("ascii"))
        finally:
            os._exit(86)
