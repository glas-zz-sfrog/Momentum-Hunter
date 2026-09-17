using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text.Json.Nodes;

namespace MomentumHunter.ContinuousServiceHost;

[System.Runtime.Versioning.SupportedOSPlatform("windows")]
internal static class DirectScienceAuthority
{
    private static readonly uint[] ServiceRights = [1, 2, 4, 8, 16, 32, 64, 128, 256, 65536, 131072, 262144, 524288];
    private static readonly uint[] FileWriteRights = [2, 4, 16, 256, 65536, 262144, 524288];
    private static readonly string[] CustodyNamespaces = ["staging", "requests", "derived", "private", "claims", "receipts", "arrivals", "custody", "cursors"];
    internal static JsonObject Inspect(string serviceName, JsonObject plan, JsonObject config, string configPath,
        ScienceQualificationTargets? qualificationTargets = null)
    {
        var api = new NativeWindowsTokenQueries();
        var inspector = new WindowsScienceTokenInspection(api);
        var opened = api.OpenProcess(0x8, out var token);
        if (!opened.Success) throw new Win32Exception(opened.Win32Error ?? 0, "SCIENCE_OWN_TOKEN_QUERY");
        TokenObservation observed;
        try { observed = inspector.Capture(token, "SCM_DIRECT_BEFORE_PYTHON", "own-SCM-service", opened.Api, 0x8); }
        finally { api.Close(token); }
        var thread = inspector.CaptureThread("SCM_DIRECT_AUTHORITY_THREAD");
        var provenance = qualificationTargets?.RestrictedServiceProvenance;
        var failures = DirectScienceTokenContract.Failures(observed, thread, serviceName, provenance).ToList();
        var result = JsonSerializerNode(new { observed, thread, scmRestrictedServiceProvenance = provenance });
        using var process = System.Diagnostics.Process.GetCurrentProcess();
        result["processId"] = process.Id;
        result["processBirth"] = process.StartTime.ToUniversalTime().ToFileTimeUtc();
        result["parentProcessId"] = ParentProcessId();
        result["parentIdentityVerification"] = "SUPERVISOR_MUST_BIND_TO_SCM";
        var rows = new JsonArray();
        result["checks"] = rows;
        result["serviceTargetScope"] = qualificationTargets == null ? "CANONICAL_PRODUCTION_NAMES" : "ISOLATED_REPLICA_TARGETS_ONLY";
        if (qualificationTargets != null) result["qualificationTargetBinding"] = qualificationTargets.Evidence();
        if (failures.Count == 0)
        {
            if (plan["profile"]?.GetValue<string>() != "SCIENCE_EFFECTIVE_AUTHORITY_SCIENCE007_V2" ||
                plan["serviceName"]?.GetValue<string>() != serviceName ||
                plan["serviceSid"]?.GetValue<string>() != ScienceServiceDaclPolicy.ServiceSid(serviceName) ||
                plan["instanceRoot"]?.GetValue<string>() != config["host"]!["instanceRoot"]!.GetValue<string>())
                throw new InvalidDataException("SCIENCE_AUTHORITY_PLAN_NOT_BOUND");
            foreach (var name in qualificationTargets?.Names ?? ScienceServiceDaclPolicy.Targets)
            foreach (var right in ServiceRights)
            {
                if (failures.Count > 0) break;
                var decision = ServiceAccess(name, right);
                rows.Add(JsonSerializerNode(new { resource = name, kind = "service", right, decision, expected = "DENIED" }));
                if (decision != 5) failures.Add("PRODUCTION_SERVICE_ACCESS_NOT_DENIED:" + name + ":" + right);
            }
            var requiredRoles = new HashSet<string>(StringComparer.Ordinal) {
                "runtimeSource", "engineState", "providerSecret", "accountSecret", "brokerSecret",
                "writerKey", "mhParent", "schedulerStorage", "productionEvidence", "productionConfig",
                "publication", "scienceCustody", "scienceLog", "scienceGeneration", "nonsecretConfiguration",
                "upstreamGenerations", "qualificationWriterKey"
            };
            var boundPaths = new Dictionary<string, string>(StringComparer.Ordinal) {
                ["runtimeSource"] = config["installRoot"]!.GetValue<string>(),
                ["publication"] = config["researchFactExportV2"]!["exportRoot"]!.GetValue<string>(),
                ["scienceCustody"] = config["host"]!["science"]!["stateRoot"]!.GetValue<string>(),
                ["scienceLog"] = Path.Combine(config["logRoot"]!.GetValue<string>(), "science"),
                ["scienceGeneration"] = Path.Combine(config["hostStateRoot"]!.GetValue<string>(), "science"),
                ["upstreamGenerations"] = config["hostStateRoot"]!.GetValue<string>(),
                ["qualificationWriterKey"] = config["ipcKeyPath"]!.GetValue<string>(),
                ["nonsecretConfiguration"] = configPath,
                ["mhParent"] = @"C:\ProgramData\MomentumHunter",
                ["schedulerStorage"] = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "System32", "Tasks")
            };
            var custodyRoots = config["host"]!["science"]!["custodyPolicy"]!["roots"]!.AsArray();
            if (custodyRoots.Count != CustodyNamespaces.Length)
                throw new InvalidDataException("SCIENCE007_CUSTODY_ROOTS_INCOMPLETE");
            foreach (var custodyNamespace in CustodyNamespaces)
            {
                var binding = custodyRoots.Single(x => x!["namespace"]!.GetValue<string>() == custodyNamespace)!;
                var scienceRoot = config["host"]!["science"]!["stateRoot"]!.GetValue<string>();
                var expected = custodyNamespace == "cursors" ? Path.Combine(scienceRoot, "reader", "cursors") : Path.Combine(scienceRoot, custodyNamespace);
                if (!Path.GetFullPath(binding["path"]!.GetValue<string>()).Equals(Path.GetFullPath(expected), StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("SCIENCE007_CUSTODY_ROOT_NOT_HOST_BOUND");
                var role = "scienceStorage:" + custodyNamespace;
                requiredRoles.Add(role);
                boundPaths.Add(role, expected);
            }
            var present = new HashSet<string>(StringComparer.Ordinal);
            foreach (var node in plan["resources"]!.AsArray())
            {
                if (failures.Count > 0) break;
                var item = node!.AsObject();
                var role = item["role"]!.GetValue<string>();
                if (!requiredRoles.Contains(role) || !present.Add(role))
                    throw new InvalidDataException("AUTHORITY_RESOURCE_UNKNOWN_OR_DUPLICATE:" + role);
                var path = item["path"]!.GetValue<string>();
                var directory = item["directory"]!.GetValue<bool>();
                if (!Path.IsPathFullyQualified(path) || path.StartsWith(@"\\", StringComparison.Ordinal))
                    throw new InvalidDataException("AUTHORITY_PATH_NOT_LOCAL_ABSOLUTE");
                var exists = item["exists"]!.GetValue<bool>();
                if (boundPaths.TryGetValue(role, out var bound) && !Path.GetFullPath(path).Equals(Path.GetFullPath(bound), StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("AUTHORITY_RESOURCE_NOT_CONFIG_BOUND:" + role);
                var custodyRole = role.StartsWith("scienceStorage:", StringComparison.Ordinal);
                if (custodyRole && (!directory || !exists))
                    throw new InvalidDataException("SCIENCE007_FIXED_CUSTODY_ROOT_UNAVAILABLE");
                var custodyTransport = role is "scienceStorage:staging" or "scienceStorage:requests" or "scienceStorage:derived";
                var requiredRead = (custodyRole && role != "scienceStorage:private") || role is "runtimeSource" or "publication" or "scienceCustody" or "scienceLog" or "scienceGeneration" or "nonsecretConfiguration" or "upstreamGenerations";
                var requiredWrite = role is "scienceLog" or "scienceGeneration";
                var deniedRead = role is "providerSecret" or "accountSecret" or "brokerSecret" or "writerKey" or "qualificationWriterKey" or "scienceStorage:private";
                var checks = new List<(uint Right, bool Allowed)>();
                if (requiredRead || deniedRead) checks.Add((1, requiredRead));
                checks.AddRange(FileWriteRights.Select(r => (r, requiredWrite || (custodyTransport && r is 2 or 4))));
                if (directory) checks.Add((64, requiredWrite || custodyTransport));
                // Modify does not grant ownership/DACL changes, even in Science roots.
                for (var index = 0; index < checks.Count; index++)
                    if (checks[index].Right is 262144 or 524288) checks[index] = (checks[index].Right, false);
                foreach (var check in checks)
                {
                    var error = FileAccess(path, directory, check.Right);
                    var good = exists ? error == (check.Allowed ? 0 : 5) : !check.Allowed && error is 2 or 3;
                    rows.Add(JsonSerializerNode(new { resource = role, path, directory, check.Right, check.Allowed,
                        error, expectedExists = exists, result = good ? exists ? "PASS" : "ABSENT_NOT_DENIAL" : "FAIL" }));
                    if (!good) { failures.Add("FILESYSTEM_AUTHORITY_MISMATCH:" + role + ":" + check.Right); break; }
                }
            }
            if (failures.Count == 0 && !requiredRoles.IsSubsetOf(present)) failures.Add("AUTHORITY_CATALOG_INCOMPLETE");
        }
        result["failures"] = JsonSerializerNode(new { values = failures })["values"]!.DeepClone();
        result["status"] = failures.Count == 0 ? "PASS" : "FAIL";
        result["credentialPayloadRead"] = false;
        result["serviceControlCalled"] = false;
        result["observedAt"] = DateTimeOffset.UtcNow.ToString("O");
        return result;
    }

    private static long ParentProcessId()
    {
        var status = NtQueryInformationProcess(new nint(-1), 0, out var info, Marshal.SizeOf<BasicInformation>(), out _);
        if (status != 0 || info.ParentProcessId == 0) throw new InvalidDataException("SCM_PARENT_IDENTITY_QUERY_FAILED");
        return info.ParentProcessId.ToInt64();
    }
    [StructLayout(LayoutKind.Sequential)] private struct BasicInformation
    { public nint Reserved1, Peb, Reserved2A, Reserved2B, ProcessId, ParentProcessId; }
    [DllImport("ntdll.dll")] private static extern int NtQueryInformationProcess(nint process, int kind, out BasicInformation info, int size, out int returned);

    private static JsonObject JsonSerializerNode(object value) => System.Text.Json.JsonSerializer.SerializeToNode(value)!.AsObject();
    private static int ServiceAccess(string name, uint access)
    {
        var manager = OpenSCManagerW(null, null, 1);
        if (manager == 0) throw new Win32Exception(Marshal.GetLastWin32Error(), "SCM_CONNECT_UNPROVEN");
        try
        {
            var service = OpenServiceW(manager, name, access);
            var error = service == 0 ? Marshal.GetLastWin32Error() : 0;
            if (service != 0 && !CloseServiceHandle(service)) throw new Win32Exception(Marshal.GetLastWin32Error());
            return error;
        }
        finally { if (!CloseServiceHandle(manager)) throw new Win32Exception(Marshal.GetLastWin32Error()); }
    }
    private static int FileAccess(string path, bool directory, uint access)
    {
        var file = CreateFileW(path, access, 7, 0, 3, 0x00200000u | (directory ? 0x02000000u : 0), 0);
        var error = file == -1 ? Marshal.GetLastWin32Error() : 0;
        if (file != -1 && !CloseHandle(file)) throw new Win32Exception(Marshal.GetLastWin32Error());
        return error;
    }
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern nint OpenSCManagerW(string? machine, string? database, uint access);
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern nint OpenServiceW(nint manager, string name, uint access);
    [DllImport("advapi32.dll", SetLastError = true)] private static extern bool CloseServiceHandle(nint handle);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern nint CreateFileW(string path, uint access, uint share, nint security, uint disposition, uint flags, nint template);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool CloseHandle(nint handle);
}
