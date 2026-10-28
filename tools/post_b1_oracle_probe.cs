// .NET Framework 4.8 oracle. Input hex is decoded as raw UTF-16 code units.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
[assembly: TargetFramework(".NETFramework,Version=v4.8")]

public static class PostB1OracleProbe
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern int CompareStringEx(string locale, uint flags, string first,
        int firstLength, string second, int secondLength, IntPtr version,
        IntPtr reserved, IntPtr parameter);

    [StructLayout(LayoutKind.Sequential)]
    public struct NlsVersion {
        public uint size, version, definedVersion, effectiveId;
        public Guid customVersion;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool GetNLSVersionEx(int function, string locale, ref NlsVersion version);

    static string Decode(string hex)
    {
        if (hex.Length % 4 != 0) throw new ArgumentException("Invalid UTF-16LE hex length");
        char[] chars = new char[hex.Length / 4];
        for (int i = 0; i < chars.Length; i++)
            chars[i] = (char)(int.Parse(hex.Substring(i * 4, 2), NumberStyles.HexNumber)
                | int.Parse(hex.Substring(i * 4 + 2, 2), NumberStyles.HexNumber) << 8);
        return new string(chars);
    }

    static string Hex(byte[] raw)
    {
        return BitConverter.ToString(raw).Replace("-", "").ToLowerInvariant();
    }

    static string Hash(string path)
    {
        using (var stream = File.OpenRead(path))
        using (var sha = SHA256.Create()) return Hex(sha.ComputeHash(stream));
    }

    public static int Main(string[] args)
    {
        if (args.Length != 4)
        {
            Console.Error.WriteLine("inputs.txt pairs.tsv arrays.json output.json");
            return 2;
        }
        Thread.CurrentThread.CurrentCulture = new CultureInfo("ja-JP");
        Thread.CurrentThread.CurrentUICulture = new CultureInfo("ja-JP");
        var hexes = File.ReadAllLines(args[0]);
        var values = Array.ConvertAll(hexes, Decode);
        var serializer = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
        var arrays = serializer.Deserialize<List<Dictionary<string, object>>>(File.ReadAllText(args[2]));
        var compare = CultureInfo.CurrentCulture.CompareInfo;
        var pairs = new List<object>();
        foreach (var line in File.ReadAllLines(args[1]))
        {
            if (line.Length == 0) continue;
            var parts = line.Split('\t');
            int li = int.Parse(parts[1]), ri = int.Parse(parts[2]);
            string left = values[li], right = values[ri];
            int result = CompareStringEx("ja-JP", 0x08000000, left, left.Length,
                right, right.Length, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
            if (result == 0) throw new System.ComponentModel.Win32Exception();
            pairs.Add(new {
                group = parts[0], left = li, right = ri,
                CompareTo_sign = Math.Sign(left.CompareTo(right)),
                CompareInfo_None_sign = Math.Sign(compare.Compare(left, right, CompareOptions.None)),
                NLS_sign = result - 2
            });
        }
        var sorts = new List<object>();
        foreach (var plan in arrays)
        {
            var ids = (ArrayList)plan["inputs"];
            var items = new List<KeyValuePair<string, int>>();
            for (int i = 0; i < ids.Count; i++)
                items.Add(new KeyValuePair<string, int>(values[Convert.ToInt32(ids[i])], i));
            var calls = new List<object>();
            Comparison<KeyValuePair<string, int>> cmp = (left, right) => {
                int sign = Math.Sign(left.Key.CompareTo(right.Key));
                calls.Add(new { call_index = calls.Count, left_original_row = left.Value,
                    right_original_row = right.Value, comparison_sign = sign });
                return sign;
            };
            string error = null, message = null;
            try { items.Sort(cmp); }
            catch (Exception ex) { error = ex.GetType().FullName; message = ex.Message; }
            var order = new List<int>();
            foreach (var row in items) order.Add(row.Value);
            sorts.Add(new { name = (string)plan["name"], count = items.Count,
                exception = error, message = message, order = order, calls = calls });
        }
        var keys = new List<string>();
        foreach (string value in values) keys.Add(Hex(compare.GetSortKey(value, CompareOptions.None).KeyData));
        var version = compare.Version;
        var nls = new NlsVersion(); nls.size = (uint)Marshal.SizeOf(typeof(NlsVersion));
        if (!GetNLSVersionEx(1, "ja-JP", ref nls)) throw new System.ComponentModel.Win32Exception();
        var report = new {
            schema = "r49-framework-oracle-1", culture = "ja-JP", compare_options = "None",
            target_framework = ".NETFramework,Version=v4.8", clr = Environment.Version.ToString(),
            framework_file_version = FileVersionInfo.GetVersionInfo(typeof(object).Assembly.Location).FileVersion,
            os = Environment.OSVersion.VersionString, nls_version = version.FullVersion,
            nls_sort_id = version.SortId.ToString(),
            nls_native_version = nls.version, nls_defined_version = nls.definedVersion,
            nls_effective_id = nls.effectiveId, nls_native_guid = nls.customVersion.ToString(),
            nls_flags = "0x08000000",
            framework_release = Microsoft.Win32.Registry.GetValue(@"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full", "Release", null),
            os_product = Microsoft.Win32.Registry.GetValue(@"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows NT\CurrentVersion", "ProductName", null),
            os_build = Microsoft.Win32.Registry.GetValue(@"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows NT\CurrentVersion", "CurrentBuildNumber", null),
            os_ubr = Microsoft.Win32.Registry.GetValue(@"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows NT\CurrentVersion", "UBR", null),
            mscorlib_sha256 = Hash(typeof(object).Assembly.Location),
            probe_sha256 = Hash(Assembly.GetExecutingAssembly().Location),
            inputs_sha256 = Hash(args[0]), pairs_sha256 = Hash(args[1]), arrays_sha256 = Hash(args[2]),
            inputs_utf16le_hex = hexes, sort_keys_hex = keys, pairs = pairs, sorts = sorts
        };
        File.WriteAllText(args[3], serializer.Serialize(report), new UTF8Encoding(false));
        Console.WriteLine("pairs=" + pairs.Count + " sorts=" + sorts.Count);
        return 0;
    }
}
