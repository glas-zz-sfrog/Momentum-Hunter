namespace MomentumHunter.ContinuousServiceHost;

internal static class ScienceMutableCustodyContract
{
    internal static string[] Namespaces(int version) => version switch
    {
        1 => ["staging", "requests", "derived", "private", "claims", "receipts", "arrivals", "custody", "cursors"],
        2 => ["staging", "requests", "derived", "private", "claims", "receipts", "arrivals", "custody", "cursors", "owner", "scratch"],
        _ => throw new InvalidDataException("UNKNOWN_CUSTODY_POLICY_VERSION")
    };

    internal static string RootPath(string root, string name, int version)
    {
        if (!Namespaces(version).Contains(name, StringComparer.Ordinal))
            throw new InvalidDataException("UNKNOWN_CUSTODY_NAMESPACE");
        if (version == 2)
            switch (name)
            {
                case "owner": return Path.Combine(root, "mutable-v2", "owner-lease");
                case "derived": return Path.Combine(root, "mutable-v2", "reader-lock");
                case "scratch": return Path.Combine(root, "mutable-v2", "transport-scratch");
                case "staging": return Path.Combine(root, "staging-v2");
                case "requests": return Path.Combine(root, "requests-v2");
            }
        return name == "cursors" ? Path.Combine(root, "reader", "cursors") : Path.Combine(root, name);
    }

    internal static bool MutableParentRight(int version, uint right)
    {
        _ = Namespaces(version);
        return right == 2 || (version == 1 && right is 4 or 64);
    }
}
