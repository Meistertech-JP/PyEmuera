// Neutral r45 diagnostic probe. Compile and execute only on the recorded
// Windows/.NET Framework host; no native observations are supplied here.
// KeyData is opaque. No Unicode normalization or zero-byte stripping occurs.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Text;
using System.Threading;

[assembly: TargetFramework(".NETFramework,Version=v4.8")]

public static class SortKeyProbeR45
{
    const uint LCMAP_SORTKEY = 0x00000400;
    const uint NORM_LINGUISTIC_CASING = 0x08000000;
    // LCMAP_LINGUISTIC_CASING (0x01000000) is a different casing-mapping
    // flag restricted to lowercase/uppercase. It is deliberately not used.

    [StructLayout(LayoutKind.Sequential)]
    public struct NlsVersion
    {
        public uint size, version, definedVersion, effectiveId;
        public Guid customVersion;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode,
        ExactSpelling = true, SetLastError = true)]
    static extern int LCMapStringEx(string locale, uint flags,
        string source, int sourceLength, [Out] byte[] target, int targetBytes,
        IntPtr version, IntPtr reserved, IntPtr sortHandle);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode,
        ExactSpelling = true, SetLastError = true)]
    static extern int CompareStringEx(string locale, uint flags,
        string left, int leftLength, string right, int rightLength,
        IntPtr version, IntPtr reserved, IntPtr parameter);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode,
        ExactSpelling = true, SetLastError = true)]
    static extern bool GetNLSVersionEx(int function, string locale, ref NlsVersion version);

    sealed class NativeKey
    {
        public byte[] validBytes;
        public Dictionary<string, object> record;
    }

    static Dictionary<string, object> Obj(params object[] args)
    {
        var result = new Dictionary<string, object>();
        for (int index = 0; index < args.Length; index += 2)
            result[(string)args[index]] = args[index + 1];
        return result;
    }

    static string Quote(string value)
    {
        var result = new StringBuilder("\"");
        foreach (char unit in value)
            result.Append("\\u").Append(((int)unit).ToString("x4", CultureInfo.InvariantCulture));
        return result.Append('"').ToString();
    }

    static string Json(object value)
    {
        if (value == null) return "null";
        if (value is string) return Quote((string)value);
        if (value is bool) return (bool)value ? "true" : "false";
        if (value is IDictionary)
        {
            var fields = new List<string>();
            foreach (DictionaryEntry entry in (IDictionary)value)
                fields.Add(Quote((string)entry.Key) + ":" + Json(entry.Value));
            return "{" + String.Join(",", fields.ToArray()) + "}";
        }
        if (value is IEnumerable)
        {
            var items = new List<string>();
            foreach (object item in (IEnumerable)value) items.Add(Json(item));
            return "[" + String.Join(",", items.ToArray()) + "]";
        }
        return Convert.ToString(value, CultureInfo.InvariantCulture);
    }

    static string UnitHex(string text)
    {
        var result = new StringBuilder();
        foreach (char unit in text)
        {
            result.Append(((int)unit & 255).ToString("x2", CultureInfo.InvariantCulture));
            result.Append(((int)unit >> 8).ToString("x2", CultureInfo.InvariantCulture));
        }
        return result.ToString();
    }

    static string DecodeHex(string value)
    {
        if (value.Length % 4 != 0)
            throw new ArgumentException("Complete UTF-16LE code units required");
        var units = new char[value.Length / 4];
        for (int index = 0; index < units.Length; index++)
        {
            int low = Int32.Parse(value.Substring(index * 4, 2),
                NumberStyles.HexNumber, CultureInfo.InvariantCulture);
            int high = Int32.Parse(value.Substring(index * 4 + 2, 2),
                NumberStyles.HexNumber, CultureInfo.InvariantCulture);
            units[index] = (char)(low | (high << 8));
        }
        return new string(units);
    }

    static string ByteHex(byte[] value)
    {
        return value == null ? null : BitConverter.ToString(value).Replace("-", "").ToLowerInvariant();
    }

    static string Hash(byte[] bytes)
    {
        using (var hash = System.Security.Cryptography.SHA256.Create())
            return ByteHex(hash.ComputeHash(bytes));
    }

    static string FileHash(string path)
    {
        return Hash(File.ReadAllBytes(path));
    }

    static Dictionary<string, object> ExceptionRecord(Exception error)
    {
        return Obj("type", error.GetType().FullName, "message", error.Message,
            "HResult", error.HResult);
    }

    static int ByteCompare(byte[] left, byte[] right)
    {
        int count = Math.Min(left.Length, right.Length);
        for (int index = 0; index < count; index++)
        {
            if (left[index] < right[index]) return -1;
            if (left[index] > right[index]) return 1;
        }
        return Math.Sign(left.Length.CompareTo(right.Length));
    }

    static object OptionalByteCompare(byte[] left, byte[] right)
    {
        return left == null || right == null ? (object)null : ByteCompare(left, right);
    }

    static NativeKey GetNativeKey(string culture, string source, uint flags)
    {
        var record = Obj("api", "LCMapStringEx", "flags_uint", flags,
            "flags_hex", "0x" + flags.ToString("x8", CultureInfo.InvariantCulture),
            "source_utf16_code_units", source.Length, "input_normalization", null);
        int required = LCMapStringEx(culture, flags, source, source.Length,
            null, 0, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
        int queryError = required == 0 ? Marshal.GetLastWin32Error() : 0;
        record["query_return"] = required;
        record["query_error"] = queryError;
        record["query_succeeded"] = required > 0;
        var result = new NativeKey();
        result.record = record;
        if (required == 0)
        {
            record["write_attempted"] = false;
            record["valid"] = false;
            record["key_data_hex"] = null;
            return result;
        }
        var buffer = new byte[required];
        int returned = LCMapStringEx(culture, flags, source, source.Length,
            buffer, buffer.Length, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
        int writeError = returned == 0 ? Marshal.GetLastWin32Error() : 0;
        record["write_attempted"] = true;
        record["allocated_bytes"] = buffer.Length;
        record["write_return"] = returned;
        record["write_error"] = writeError;
        record["raw_buffer_hex"] = ByteHex(buffer);
        bool valid = returned > 0 && returned <= buffer.Length;
        record["valid"] = valid;
        if (valid)
        {
            result.validBytes = new byte[returned];
            Array.Copy(buffer, result.validBytes, returned);
            record["key_data_hex"] = ByteHex(result.validBytes);
            record["key_data_sha256"] = Hash(result.validBytes);
        }
        else
        {
            // The API documents that any partial failure result is invalid.
            record["key_data_hex"] = null;
            record["key_data_sha256"] = null;
        }
        return result;
    }

    static object SignedOperation(Func<int> operation, Dictionary<string, object> errors, string name)
    {
        try { return Math.Sign(operation()); }
        catch (Exception error)
        {
            errors[name] = ExceptionRecord(error);
            return null;
        }
    }

    public static int Main(string[] args)
    {
        if (args.Length < 3 || args.Length > 4)
        {
            Console.Error.WriteLine("windows_sortkey_probe_r45.exe INPUT_HEX PAIRS_TSV OUTPUT_JSON [CULTURE]");
            return 2;
        }
        string culture = args.Length == 4 ? args[3] : "ja-JP";
        Thread.CurrentThread.CurrentCulture = new CultureInfo(culture);
        Thread.CurrentThread.CurrentUICulture = new CultureInfo(culture);
        CompareInfo comparer = CultureInfo.CurrentCulture.CompareInfo;
        var values = new List<string>();
        var originalHex = new List<string>();
        var frameworkKeys = new List<SortKey>();
        var plainKeys = new List<NativeKey>();
        var casingKeys = new List<NativeKey>();
        var keyRecords = new List<object>();
        foreach (string hex in File.ReadAllLines(args[0]))
        {
            string text = DecodeHex(hex);
            values.Add(text);
            originalHex.Add(UnitHex(text));
            SortKey key = null;
            var framework = Obj("api", "CompareInfo.GetSortKey", "CompareOptions", "None");
            try
            {
                key = comparer.GetSortKey(text, CompareOptions.None);
                byte[] bytes = key.KeyData;
                framework["valid"] = true;
                framework["key_data_hex"] = ByteHex(bytes);
                framework["key_data_sha256"] = Hash(bytes);
                framework["key_data_bytes"] = bytes.Length;
                framework["original_string_utf16le_hex"] = UnitHex(key.OriginalString);
            }
            catch (Exception error)
            {
                framework["valid"] = false;
                framework["exception"] = ExceptionRecord(error);
            }
            frameworkKeys.Add(key);
            NativeKey plain = GetNativeKey(culture, text, LCMAP_SORTKEY);
            NativeKey casing = GetNativeKey(culture, text, LCMAP_SORTKEY | NORM_LINGUISTIC_CASING);
            plainKeys.Add(plain);
            casingKeys.Add(casing);
            keyRecords.Add(Obj("input_index", values.Count - 1,
                "original_utf16le_hex", UnitHex(text), "utf16_code_units", text.Length,
                "Framework_None", framework, "LCMAP_SORTKEY", plain.record,
                "LCMAP_SORTKEY_NORM_LINGUISTIC_CASING", casing.record,
                "framework_vs_plain_key_bytes_equal", key == null || plain.validBytes == null
                    ? (object)null : ByteCompare(key.KeyData, plain.validBytes) == 0,
                "framework_vs_linguistic_key_bytes_equal", key == null || casing.validBytes == null
                    ? (object)null : ByteCompare(key.KeyData, casing.validBytes) == 0));
        }
        var pairs = new List<object>();
        foreach (string line in File.ReadAllLines(args[1]))
        {
            string[] fields = line.Split('\t');
            int left = Int32.Parse(fields[0], CultureInfo.InvariantCulture);
            int right = Int32.Parse(fields[1], CultureInfo.InvariantCulture);
            var errors = new Dictionary<string, object>();
            int rawNls = CompareStringEx(culture, NORM_LINGUISTIC_CASING,
                values[left], values[left].Length, values[right], values[right].Length,
                IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
            int nlsError = rawNls == 0 ? Marshal.GetLastWin32Error() : 0;
            pairs.Add(Obj("left_index", left, "right_index", right,
                "left_utf16le_hex", originalHex[left], "right_utf16le_hex", originalHex[right],
                "CompareTo_sign", SignedOperation(() => values[left].CompareTo(values[right]), errors, "CompareTo"),
                "CompareInfo_None_sign", SignedOperation(() => comparer.Compare(values[left], values[right], CompareOptions.None), errors, "CompareInfo"),
                "CompareStringEx_sign", rawNls == 0 ? (object)null : rawNls - 2,
                "CompareStringEx_return", rawNls, "CompareStringEx_error", nlsError,
                "CompareStringEx_flags", NORM_LINGUISTIC_CASING,
                "Framework_SortKey_Compare_sign", frameworkKeys[left] == null || frameworkKeys[right] == null
                    ? null : SignedOperation(() => SortKey.Compare(frameworkKeys[left], frameworkKeys[right]), errors, "SortKey.Compare"),
                "Framework_KeyData_byte_compare_sign", frameworkKeys[left] == null || frameworkKeys[right] == null
                    ? (object)null : ByteCompare(frameworkKeys[left].KeyData, frameworkKeys[right].KeyData),
                "LCMAP_SORTKEY_byte_compare_sign", OptionalByteCompare(plainKeys[left].validBytes, plainKeys[right].validBytes),
                "LCMAP_SORTKEY_NORM_LINGUISTIC_CASING_byte_compare_sign", OptionalByteCompare(casingKeys[left].validBytes, casingKeys[right].validBytes),
                "exceptions", errors));
        }
        NlsVersion version = new NlsVersion();
        version.size = (uint)Marshal.SizeOf(typeof(NlsVersion));
        bool versionOk = GetNLSVersionEx(1, culture, ref version);
        int versionError = versionOk ? 0 : Marshal.GetLastWin32Error();
        string mscorlib = typeof(string).Assembly.Location;
        var identity = Obj("CurrentCulture", CultureInfo.CurrentCulture.Name,
            "CurrentUICulture", CultureInfo.CurrentUICulture.Name,
            "CompareOptions", "None", "CLR", Environment.Version.ToString(),
            "TargetFramework", ".NETFramework,Version=v4.8", "OS_version_reported", Environment.OSVersion.Version.ToString(),
            "mscorlib_file", mscorlib, "mscorlib_file_sha256", FileHash(mscorlib),
            "mscorlib_assembly", typeof(string).Assembly.FullName,
            "mscorlib_file_version", System.Diagnostics.FileVersionInfo.GetVersionInfo(mscorlib).FileVersion,
            "Framework_release", Microsoft.Win32.Registry.GetValue(@"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full", "Release", null),
            "OS_registry_build", Microsoft.Win32.Registry.GetValue(@"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows NT\CurrentVersion", "CurrentBuildNumber", null),
            "NLS_version_success", versionOk, "NLS_version", version.version,
            "NLS_defined_version", version.definedVersion, "NLS_effective_id", version.effectiveId,
            "NLS_sort_GUID", version.customVersion.ToString(), "NLS_version_error", versionError);
        var report = Obj("schema", "r45-framework-unary-sortkey-probe-1", "identity", identity,
            "inputs_sha256", FileHash(args[0]), "pair_plan_sha256", FileHash(args[1]),
            "inputs_utf16le_hex", originalHex, "key_records", keyRecords, "comparisons", pairs,
            "sort_keys_opaque", true, "zero_bytes_stripped", false,
            "flags_scope", "NORM_LINGUISTIC_CASING is documented with LCMAP_SORTKEY; LCMAP_LINGUISTIC_CASING is not used. Failures remain raw observations.",
            "scope", "Native data exists only after this probe is compiled and executed on the recorded Windows host. No assumption of CompareStringEx/SortKey sign or byte equivalence.");
        File.WriteAllText(args[2], Json(report) + "\n", new UTF8Encoding(false));
        Console.WriteLine("inputs=" + values.Count + " pairs=" + pairs.Count + " key-sources=3");
        return 0;
    }
}
