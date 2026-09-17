using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MomentumHunter.ContinuousServiceHost;

[System.Runtime.Versioning.SupportedOSPlatform("windows")]
internal sealed class DirectScienceImage : IDisposable
{
    private readonly List<FileStream> leases = [];
    private readonly string root;
    internal JsonObject Manifest { get; }
    internal int? NetworkDeniedAttempts { get; private set; }
    internal DirectScienceImage(ContinuousServiceOptions options, JsonObject config)
    {
        root = Path.GetFullPath(config["installRoot"]!.GetValue<string>());
        var path = Resolve("science-image-manifest.json");
        var expected = config["host"]!["science"]!["imageManifestSha256"]!.GetValue<string>();
        var bytes = File.ReadAllBytes(path);
        if (Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() != expected)
            throw new InvalidDataException("SCIENCE_IMAGE_MANIFEST_HASH_MISMATCH");
        Manifest = JsonNode.Parse(bytes)!.AsObject();
        if (Manifest["profile"]?.GetValue<string>() != "SCIENCE_DIRECT_IMAGE_V1")
            throw new InvalidDataException("SCIENCE_IMAGE_PROFILE_MISMATCH");
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        try
        {
            foreach (var item in Manifest["files"]!.AsArray())
            {
                var relative = item!["path"]!.GetValue<string>();
                if (!seen.Add(relative)) throw new InvalidDataException("SCIENCE_IMAGE_DUPLICATE_PATH");
                var stream = new FileStream(Resolve(relative), FileMode.Open, FileAccess.Read, FileShare.Read);
                leases.Add(stream);
                if (stream.Length != item["length"]!.GetValue<long>() ||
                    Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant() != item["sha256"]!.GetValue<string>())
                    throw new InvalidDataException("SCIENCE_IMAGE_BYTE_MISMATCH:" + relative);
            }
            foreach (var file in new[] { Manifest["pythonDll"]!.GetValue<string>(), "science-authority.json",
                Path.GetRelativePath(root, Environment.ProcessPath!).Replace('\\', '/'),
                Path.GetRelativePath(root, typeof(DirectScienceImage).Assembly.Location).Replace('\\', '/') })
                if (!seen.Contains(file)) throw new InvalidDataException("SCIENCE_IMAGE_REQUIRED_FILE_UNBOUND:" + file);
            if (!Path.GetFullPath(options.RepositoryRoot).Equals(Resolve("source"), StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("SCIENCE_SOURCE_ROOT_MISMATCH");
            if (!seen.Contains("source/momentum_hunter/continuous_science_service.py"))
                throw new InvalidDataException("SCIENCE_ENTRYPOINT_UNBOUND");
            // No additional Python/native file may hide beside the reviewed files.
            var actual = Inventory(root)
                .Select(p => Path.GetRelativePath(root, p).Replace('\\', '/'))
                .Where(p => p != "science-image-manifest.json").ToHashSet(StringComparer.OrdinalIgnoreCase);
            if (!actual.SetEquals(seen)) throw new InvalidDataException("SCIENCE_IMAGE_INVENTORY_DRIFT");
        }
        catch { Dispose(); throw; }
    }
    private static IEnumerable<string> Inventory(string path)
    {
        foreach (var item in Directory.EnumerateFileSystemEntries(path))
        {
            var attributes = File.GetAttributes(item);
            if ((attributes & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("SCIENCE_IMAGE_REPARSE_INVENTORY");
            if ((attributes & FileAttributes.Directory) != 0)
            { foreach (var nested in Inventory(item)) yield return nested; }
            else yield return item;
        }
    }
    internal string Resolve(string relative)
    {
        if (Path.IsPathFullyQualified(relative) || relative.Contains(':') || relative.Contains('\\') ||
            relative.Split('/').Any(p => p is "" or "." or ".." || p.EndsWith('.') || p.EndsWith(' ')))
            throw new InvalidDataException("SCIENCE_IMAGE_RELATIVE_PATH_INVALID");
        var full = Path.GetFullPath(Path.Combine(root, relative));
        if (!full.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("SCIENCE_IMAGE_PATH_ESCAPE");
        for (var info = new FileInfo(full) as FileSystemInfo; info != null; info = Directory.GetParent(info.FullName))
            if ((info.Attributes & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("SCIENCE_IMAGE_REPARSE_PATH");
        return full;
    }
    internal int Run(string configPath, string generation, nint stop)
    {
        var dll = Resolve(Manifest["pythonDll"]!.GetValue<string>());
        var module = LoadLibraryExW(dll, 0, 0x1100);
        if (module == 0) throw new Win32Exception(Marshal.GetLastWin32Error(), "LOAD_PINNED_CPYTHON");
        var main = Export<PyMain>(module, "Py_Main");
        var setPath = Export<PySetPath>(module, "Py_SetPath");
        var version = Marshal.PtrToStringUTF8(Export<PyVersion>(module, "Py_GetVersion")());
        if (version?.StartsWith("3.12.6 ", StringComparison.Ordinal) != true)
            throw new InvalidDataException("CPYTHON_ABI_VERSION_MISMATCH");
        var paths = Manifest["pythonPaths"]!.AsArray().Select(p => Resolve(p!.GetValue<string>())).ToArray();
        if (!paths.Contains(Resolve("source"), StringComparer.OrdinalIgnoreCase)) throw new InvalidDataException("SOURCE_IMPORT_PATH_MISSING");
        setPath(string.Join(';', paths));
        var result = Marshal.AllocHGlobal(sizeof(int) * 2);
        var argv = new List<nint>();
        nint pointers = 0;
        try
        {
            Marshal.WriteInt32(result, 2);
            Marshal.WriteInt32(result, sizeof(int), -1);
            var quoted = System.Text.Json.JsonSerializer.Serialize(configPath);
            var code = "import sys\n_denied=[0]\n" +
                "def _deny(e,a):\n if e.startswith('socket.') and e not in ('socket.__new__',):\n  _denied[0]+=1\n  raise PermissionError('SCIENCE_NETWORK_DENIED')\n" +
                "sys.addaudithook(_deny)\nimport ctypes,traceback\n_result=ctypes.c_int.from_address(" + result.ToInt64() + ")\n" +
                "try:\n from momentum_hunter.continuous_science_service import run\n _result.value=run(" + quoted + ", '" + generation + "', " + stop.ToInt64() + ")\n" +
                "except BaseException:\n _result.value=2\n traceback.print_exc()\n" +
                "finally:\n ctypes.c_int.from_address(" + (result.ToInt64() + sizeof(int)) + ").value=_denied[0]\n";
            foreach (var arg in new[] { "python", "-I", "-S", "-B", "-X", "utf8", "-c", code }) argv.Add(Marshal.StringToHGlobalUni(arg));
            pointers = Marshal.AllocHGlobal((argv.Count + 1) * IntPtr.Size);
            for (var i = 0; i < argv.Count; i++) Marshal.WriteIntPtr(pointers, i * IntPtr.Size, argv[i]);
            Marshal.WriteIntPtr(pointers, argv.Count * IntPtr.Size, 0);
            var exit = main(argv.Count, pointers);
            NetworkDeniedAttempts = Marshal.ReadInt32(result, sizeof(int));
            return exit == 0 && NetworkDeniedAttempts == 0 && Marshal.ReadInt32(result) is 0 or 3 ? Marshal.ReadInt32(result) : 2;
        }
        finally
        {
            if (pointers != 0) Marshal.FreeHGlobal(pointers);
            foreach (var arg in argv) Marshal.FreeHGlobal(arg);
            Marshal.FreeHGlobal(result);
            // Native extension modules may retain CPython pointers; never unload it.
        }
    }
    private static T Export<T>(nint module, string name) where T : Delegate
    {
        var address = GetProcAddress(module, name);
        if (address == 0) throw new Win32Exception(Marshal.GetLastWin32Error(), name);
        return Marshal.GetDelegateForFunctionPointer<T>(address);
    }
    public void Dispose() { foreach (var lease in leases) lease.Dispose(); leases.Clear(); }
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int PyMain(int argc, nint argv);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate void PySetPath([MarshalAs(UnmanagedType.LPWStr)] string path);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint PyVersion();
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern nint LoadLibraryExW(string path, nint file, uint flags);
    [DllImport("kernel32.dll", CharSet = CharSet.Ansi, ExactSpelling = true, SetLastError = true)] private static extern nint GetProcAddress(nint module, string name);
}
