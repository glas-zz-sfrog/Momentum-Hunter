import ctypes
from ctypes import wintypes
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from momentum_hunter import continuous_host_generation as generation


@unittest.skipUnless(os.name == "nt", "Windows process exit proof")
class ProcessExitSnapshotTests(unittest.TestCase):
    target_pid = 123
    target_birth = 456

    @staticmethod
    def fail_native(error):
        def fail(*args):
            ctypes.set_last_error(error)
            return 0
        return fail

    def kernel(self, pids, *, end_error=18, first_error=None, close=True, wrong_size=False):
        kernel = Mock()
        kernel.OpenProcess.side_effect = self.fail_native(5)
        kernel.CreateToolhelp32Snapshot.return_value = 99
        kernel.CloseHandle.return_value = close
        rows = iter(pids)

        def advance(handle, pointer):
            try:
                pid = next(rows)
            except StopIteration:
                ctypes.set_last_error(end_error)
                return False
            entry = pointer._obj
            entry.dwSize = 0 if wrong_size else ctypes.sizeof(entry)
            entry.th32ProcessID = pid
            return True

        if first_error is None:
            kernel.Process32FirstW.side_effect = advance
        else:
            kernel.Process32FirstW.side_effect = self.fail_native(first_error)
        kernel.Process32NextW.side_effect = advance
        return kernel

    def observed(self, kernel, *, birth=456):
        detail = {}
        with patch.object(generation.ctypes, "WinDLL", return_value=kernel):
            state = generation.process_lifetime(self.target_pid, birth, observation=detail)
        kernel.OpenProcess.assert_called_once_with(0x1000, False, self.target_pid)
        return state, detail

    def test_complete_absence_independently_proves_exit_despite_denied_handle(self):
        kernel = self.kernel([0, os.getpid(), 987])
        state, detail = self.observed(kernel)
        self.assertEqual("EXITED", state)
        self.assertEqual("COMPLETE_PROCESS_SNAPSHOT_ABSENCE", detail["operation"])
        self.assertEqual(5, detail["winerror"])
        self.assertEqual({"complete": True, "count": 3, "targetPresent": False,
                          "selfPresent": True, "operation": "Process32NextW", "winerror": 18,
                          "handleClosed": True}, detail["exitSnapshot"])
        kernel.CreateToolhelp32Snapshot.assert_called_once_with(2, 0)
        kernel.CloseHandle.assert_called_once_with(99)

    def test_denied_present_pid_remains_unknown_even_with_different_birth(self):
        for birth in (456, 789):
            with self.subTest(birth=birth):
                kernel = self.kernel([os.getpid(), self.target_pid])
                state, detail = self.observed(kernel, birth=birth)
                self.assertEqual("UNKNOWN", state)
                self.assertTrue(detail["exitSnapshot"]["targetPresent"])
                self.assertEqual("OpenProcess", detail["operation"])
                kernel.CloseHandle.assert_called_once_with(99)

    def test_no_absence_from_failed_or_empty_snapshot(self):
        for first_error in (5, 18, 299):
            with self.subTest(first_error=first_error):
                kernel = self.kernel([], first_error=first_error)
                state, detail = self.observed(kernel)
                self.assertEqual("UNKNOWN", state)
                self.assertFalse(detail["exitSnapshot"]["complete"])
                kernel.CloseHandle.assert_called_once_with(99)

    def test_snapshot_creation_failure_never_proves_exit(self):
        for handle in (None, ctypes.c_void_p(-1).value):
            with self.subTest(handle=handle):
                kernel = self.kernel([])
                kernel.CreateToolhelp32Snapshot.return_value = handle
                self.assertEqual("UNKNOWN", self.observed(kernel)[0])
                kernel.CloseHandle.assert_not_called()

    def test_partial_enumeration_error_does_not_prove_absence(self):
        for error in (0, 5, 24, 299):
            with self.subTest(error=error):
                kernel = self.kernel([os.getpid()], end_error=error)
                state, detail = self.observed(kernel)
                self.assertEqual("UNKNOWN", state)
                self.assertFalse(detail["exitSnapshot"]["complete"])

    def test_snapshot_missing_self_does_not_prove_absence(self):
        self.assertEqual("UNKNOWN", self.observed(self.kernel([0, 987]))[0])

    def test_duplicate_or_invalid_structure_does_not_prove_absence(self):
        for kernel in (self.kernel([os.getpid(), os.getpid()]),
                       self.kernel([os.getpid()], wrong_size=True)):
            state, detail = self.observed(kernel)
            self.assertEqual("UNKNOWN", state)
            self.assertEqual("SNAPSHOT_ENTRY_INVALID", detail["exitSnapshot"]["operation"])

    def test_enumeration_bound_is_not_a_complete_snapshot(self):
        kernel = self.kernel(range(65536))
        state, detail = self.observed(kernel)
        self.assertEqual("UNKNOWN", state)
        self.assertEqual("SNAPSHOT_BOUND", detail["exitSnapshot"]["operation"])
        self.assertEqual(65536, detail["exitSnapshot"]["count"])

    def test_close_failure_does_not_admit_exit(self):
        state, detail = self.observed(self.kernel([os.getpid()], close=False))
        self.assertEqual("UNKNOWN", state)
        self.assertFalse(detail["exitSnapshot"]["handleClosed"])

    def test_other_open_errors_do_not_use_snapshot(self):
        for error, expected in ((87, "EXITED"), (6, "UNKNOWN"), (299, "UNKNOWN")):
            with self.subTest(error=error):
                kernel = self.kernel([])
                kernel.OpenProcess.side_effect = self.fail_native(error)
                self.assertEqual(expected, self.observed(kernel)[0])
                kernel.CreateToolhelp32Snapshot.assert_not_called()

    def test_observation_does_not_change_native_decision_or_call_count(self):
        for pids in ([os.getpid()], [os.getpid(), self.target_pid]):
            plain, observed = self.kernel(pids), self.kernel(pids)
            with patch.object(generation.ctypes, "WinDLL", return_value=plain):
                state = generation.process_lifetime(self.target_pid, self.target_birth)
            self.assertEqual(state, self.observed(observed)[0])
            self.assertEqual([call[0] for call in plain.method_calls],
                             [call[0] for call in observed.method_calls])
            for name in ("OpenProcess", "CreateToolhelp32Snapshot", "CloseHandle"):
                self.assertEqual(getattr(plain, name).call_args_list, getattr(observed, name).call_args_list)

    def test_non_native_identity_width_never_reaches_a_native_call(self):
        cases = [(pid, 456) for pid in (0, -1, True, "123", (1 << 32) + 123, 1 << 64)]
        cases += [(123, birth) for birth in (0, -1, True, "456", 1 << 64, 1 << 256)]
        for pid, birth in cases:
            with self.subTest(pid=pid, birth=birth), patch.object(generation.ctypes, "WinDLL") as dll:
                detail = {}
                self.assertEqual("UNKNOWN", generation.process_lifetime(pid, birth, observation=detail))
                self.assertEqual("INPUT_VALIDATION", detail["operation"])
                dll.assert_not_called()

    def test_native_denied_live_process_stays_unknown_but_retained_exited_object_is_proven(self):
        child = r'''
import ctypes, json, os, sys
from ctypes import wintypes as W
k=ctypes.WinDLL("kernel32",use_last_error=True)
a=ctypes.WinDLL("advapi32",use_last_error=True)
k.GetCurrentProcess.restype=W.HANDLE
k.LocalFree.argtypes=[W.HANDLE]
a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes=[W.LPCWSTR,W.DWORD,ctypes.POINTER(W.HANDLE),ctypes.POINTER(W.DWORD)]
a.SetKernelObjectSecurity.argtypes=[W.HANDLE,W.DWORD,W.HANDLE]
sd=W.HANDLE()
if not a.ConvertStringSecurityDescriptorToSecurityDescriptorW("D:P(D;;0x1000;;;WD)(A;;GA;;;WD)",1,ctypes.byref(sd),None): raise ctypes.WinError(ctypes.get_last_error())
try:
    if not a.SetKernelObjectSecurity(k.GetCurrentProcess(),4,sd): raise ctypes.WinError(ctypes.get_last_error())
finally: k.LocalFree(sd)
print(json.dumps({"pid":os.getpid()}),flush=True)
if sys.stdin.readline()!="EXIT\n": sys.exit(9)
'''
        process = subprocess.Popen([sys._base_executable, "-I", "-c", child], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            self.assertEqual({"pid": process.pid}, json.loads(process.stdout.readline()))
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
            times = [wintypes.FILETIME() for _ in range(4)]
            self.assertTrue(kernel.GetProcessTimes(int(process._handle), *(ctypes.byref(t) for t in times)))
            birth = times[0].dwLowDateTime | (times[0].dwHighDateTime << 32)
            alive = {}
            self.assertEqual("UNKNOWN", generation.process_lifetime(process.pid, birth, observation=alive))
            self.assertEqual(5, alive["winerror"])
            self.assertTrue(alive["exitSnapshot"]["targetPresent"])
            for pid_alias, invalid_birth in ((process.pid + (1 << 32), birth),
                                             (process.pid, birth + (1 << 64))):
                invalid = {}
                self.assertEqual("UNKNOWN", generation.process_lifetime(pid_alias, invalid_birth, observation=invalid))
                self.assertEqual("INPUT_VALIDATION", invalid["operation"])
            process.stdin.write("EXIT\n")
            process.stdin.flush()
            self.assertEqual(0, process.wait(timeout=10))
            exited = {}
            self.assertEqual("EXITED", generation.process_lifetime(process.pid, birth, observation=exited))
            self.assertEqual("COMPLETE_PROCESS_SNAPSHOT_ABSENCE", exited["operation"])
            self.assertEqual(5, exited["winerror"])
            self.assertFalse(exited["exitSnapshot"]["targetPresent"])
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            process._handle.Close()
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

    def test_native_suspended_denied_process_is_not_mistaken_for_exit(self):
        import _winapi

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.DWORD)]
        advapi.SetKernelObjectSecurity.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.HANDLE]
        kernel.LocalFree.argtypes = [wintypes.HANDLE]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
        kernel.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel.ResumeThread.restype = wintypes.DWORD
        command = subprocess.list2cmdline([sys._base_executable, "-I", "-c", "pass"])
        process, thread, pid, _ = _winapi.CreateProcess(sys._base_executable, command, None, None,
                                                       False, subprocess.CREATE_NO_WINDOW | 4,
                                                       None, None, subprocess.STARTUPINFO())
        sd = wintypes.HANDLE()
        try:
            self.assertTrue(advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                "D:P(D;;0x1000;;;WD)(A;;GA;;;WD)", 1, ctypes.byref(sd), None))
            self.assertTrue(advapi.SetKernelObjectSecurity(process, 4, sd))
            times = [wintypes.FILETIME() for _ in range(4)]
            self.assertTrue(kernel.GetProcessTimes(process, *(ctypes.byref(t) for t in times)))
            birth = times[0].dwLowDateTime | (times[0].dwHighDateTime << 32)
            detail = {}
            self.assertEqual("UNKNOWN", generation.process_lifetime(pid, birth, observation=detail))
            self.assertTrue(detail["exitSnapshot"]["targetPresent"])
            self.assertEqual(5, detail["winerror"])
            self.assertEqual(1, kernel.ResumeThread(thread))
            self.assertEqual(0, _winapi.WaitForSingleObject(process, 10000))
            self.assertEqual(0, _winapi.GetExitCodeProcess(process))
        finally:
            if _winapi.WaitForSingleObject(process, 0) != 0:
                _winapi.TerminateProcess(process, 1)
                _winapi.WaitForSingleObject(process, 10000)
            _winapi.CloseHandle(thread)
            _winapi.CloseHandle(process)
            if sd:
                kernel.LocalFree(sd)


if __name__ == "__main__":
    unittest.main()
