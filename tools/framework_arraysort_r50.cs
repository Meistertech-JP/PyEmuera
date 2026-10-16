// Independent executable oracle, not a reimplementation of the sort algorithm.
// csc /r:System.Web.Extensions.dll /out:probe.exe framework_arraysort_r50.cs
// probe.exe plans.json results.json
// Default string[] cannot expose CompareTo callbacks (String is sealed).
// Tagged implements IComparable<Tagged>, selecting the SAME reference-type
// GenericArraySortHelper specialization; its calls/identities are observable.
// Every uninjected culture case also sorts real string[] independently.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.Versioning;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using Microsoft.Win32;
[assembly: TargetFramework(".NETFramework,Version=v4.8")]

public static class FrameworkArraySortR50 {
    sealed class Tagged : IComparable<Tagged> {
        public string Text;
        public int Id;
        public Context Owner;
        public int CompareTo(Tagged other) { return Owner.Compare(this, other); }
    }

    sealed class Context {
        public string Mode, ThrowKind;
        public int ThrowAt;
        public List<object> Calls = new List<object>();
        public int Compare(Tagged left, Tagged right) {
            int? sign = null;
            string error = null;
            int call = Calls.Count;
            try {
                if (call + 1 == ThrowAt) ThrowInjected(ThrowKind);
                if (left == null) throw new NullReferenceException();
                sign = right == null ? 1 : (Mode == "contradiction"
                    ? (left.Id == right.Id ? 0 : -1)
                    : Mode == "positive" ? (left.Id == right.Id ? 0 : 1)
                    : Mode == "always_negative" ? -1
                    : Math.Sign(left.Text.CompareTo(right.Text)));
                return sign.Value;
            } catch (Exception e) { error = e.GetType().FullName; throw; }
            finally {
                Calls.Add(new { comparison_call_index = call,
                    left_original_index = Id(left), right_original_index = Id(right),
                    comparison_sign = sign, exception = error });
            }
        }
    }

    static void ThrowInjected(string kind) {
        if (kind == "IndexOutOfRangeException") throw new IndexOutOfRangeException("r50 injected index");
        throw new ApplicationException("r50 injected comparison failure");
    }
    static int Id(Tagged value) { return value == null ? -1 : value.Id; }
    static string Decode(string hex) {
        if (hex == null) return null;
        char[] chars = new char[hex.Length / 4];
        for (int i = 0; i < chars.Length; i++) chars[i] = (char)(
            int.Parse(hex.Substring(i * 4, 2), NumberStyles.HexNumber)
            | int.Parse(hex.Substring(i * 4 + 2, 2), NumberStyles.HexNumber) << 8);
        return new string(chars);
    }
    static string Hex(string value) {
        if (value == null) return null;
        // Preserve arbitrary UTF-16 units instead of replacement encoding.
        var bytes = new byte[value.Length * 2];
        for (int i = 0; i < value.Length; i++) {
            bytes[i * 2] = (byte)value[i]; bytes[i * 2 + 1] = (byte)(value[i] >> 8);
        }
        return BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant();
    }
    static string Hash(string path) {
        using (var f = File.OpenRead(path)) using (var sha = SHA256.Create())
            return BitConverter.ToString(sha.ComputeHash(f)).Replace("-", "").ToLowerInvariant();
    }
    static Type Helper(Type element, bool comparable) {
        return typeof(object).Assembly.GetType("System.Collections.Generic."
            + (comparable ? "GenericArraySortHelper`1" : "ArraySortHelper`1"), true)
            .MakeGenericType(element);
    }
    static string SelectedDefaultHelper(Type element) {
        return Helper(element, false).GetProperty("Default", BindingFlags.Public | BindingFlags.Static)
            .GetValue(null, null).GetType().FullName;
    }
    static Exception Actual(Exception e) {
        return e is TargetInvocationException ? e.InnerException : e;
    }
    static void SortTagged(Tagged[] temp, Context ctx, bool back, bool heap) {
        if (!heap) {
            if (back) Array.Sort(temp, (a, b) => ctx.Compare(b, a));
            else Array.Sort(temp);
            return;
        }
        // Isolated fallback measurement: invoke the shipped private method,
        // not a copied heap algorithm. This is not a public Array.Sort case.
        var m = Helper(typeof(Tagged), !back).GetMethod("Heapsort", BindingFlags.Static | BindingFlags.NonPublic);
        object[] args = back
            ? new object[] { temp, 0, temp.Length - 1, Comparer<Tagged>.Create((a, b) => ctx.Compare(b, a)) }
            : new object[] { temp, 0, temp.Length - 1 };
        m.Invoke(null, args);
    }
    static object Direct(string[] input, bool back, bool heap) {
        string[] source = new string[input.Length + 2];
        source[0] = "outside-left"; source[source.Length - 1] = "outside-right";
        Array.Copy(input, 0, source, 1, input.Length);
        string[] temp = new string[input.Length];
        Array.Copy(source, 1, temp, 0, temp.Length);
        string error = null, inner = null;
        var calls = new List<object>();
        Comparison<string> cmp = (a, b) => {
            int? sign = null; string failure = null;
            try { sign = Math.Sign(b.CompareTo(a)); return sign.Value; }
            catch (Exception ex) { failure = ex.GetType().FullName; throw; }
            finally { calls.Add(new {comparison_call_index = calls.Count,
                left_utf16le_hex = Hex(b), right_utf16le_hex = Hex(a),
                comparison_sign = sign, exception = failure}); }
        };
        try {
            if (heap) {
                var m = Helper(typeof(string), !back).GetMethod("Heapsort", BindingFlags.Static | BindingFlags.NonPublic);
                m.Invoke(null, back ? new object[] {temp, 0, temp.Length - 1, Comparer<string>.Create(cmp)}
                    : new object[] {temp, 0, temp.Length - 1});
            } else if (back) Array.Sort(temp, cmp);
            else Array.Sort(temp);
            Array.Copy(temp, 0, source, 1, temp.Length);
        } catch (Exception ex) {
            var e = Actual(ex); error = e.GetType().FullName;
            inner = e.InnerException == null ? null : e.InnerException.GetType().FullName;
        }
        // Equal nonempty texts have distinct fresh string references. Empty
        // strings and multiple nulls have no distinguishable string identity.
        var order = new List<int>();
        foreach (var s in temp) {
            int id = -1;
            if (s != null) {
                id = -4;
                for (int i = 0; i < input.Length; i++) if (Object.ReferenceEquals(s, input[i])) {
                    if (id != -4) { id = -4; break; } id = i;
                }
            }
            order.Add(id);
        }
        return new { observation = heap ? "private Framework Heapsort<string>" : "public Array.Sort<string>",
            exception = error, inner_exception = inner,
            temporary_utf16le_hex = Array.ConvertAll(temp, Hex), order = order,
            source_utf16le_hex = Array.ConvertAll(source, Hex), calls = calls,
            forward_calls_observable = false };
    }

    static object ListRoute(string[] input, bool back, Context original) {
        // Exact List<KeyValuePair<string,int>> construction used by ARRAYMSORT:
        // successive Add, including default struct entries in unused capacity.
        var ctx = new Context {Mode = original.Mode, ThrowAt = original.ThrowAt, ThrowKind = original.ThrowKind};
        var list = new List<KeyValuePair<string, int>>();
        for (int i = 0; i < input.Length; i++) list.Add(new KeyValuePair<string, int>(input[i], i));
        string error = null, inner = null;
        try {
            list.Sort((a, b) => {
                var left = new Tagged {Text = a.Key, Id = a.Value, Owner = ctx};
                var right = new Tagged {Text = b.Key, Id = b.Value, Owner = ctx};
                return back ? ctx.Compare(right, left) : ctx.Compare(left, right);
            });
        } catch (Exception e) {
            error = e.GetType().FullName;
            inner = e.InnerException == null ? null : e.InnerException.GetType().FullName;
        }
        var order = new List<int>(); foreach (var row in list) order.Add(row.Value);
        return new { count = list.Count, capacity = list.Capacity, order = order,
            calls = ctx.Calls, exception = error, inner_exception = inner };
    }

    public static int Main(string[] args) {
        if (args.Length != 2) { Console.Error.WriteLine("plans.json results.json"); return 2; }
        Thread.CurrentThread.CurrentCulture = new CultureInfo("ja-JP");
        Thread.CurrentThread.CurrentUICulture = new CultureInfo("ja-JP");
        var serializer = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
        var plans = serializer.Deserialize<List<Dictionary<string, object>>>(File.ReadAllText(args[0]));
        var results = new List<object>();
        foreach (var plan in plans) {
            var hexes = (ArrayList)plan["inputs_utf16le_hex"];
            bool back = (string)plan["direction"] == "BACK";
            bool heap = (string)plan["algorithm"] == "forced_heap";
            var ctx = new Context { Mode = (string)plan["mode"],
                ThrowAt = Convert.ToInt32(plan["throw_at"]), ThrowKind = (string)plan["throw_kind"] };
            var input = new string[hexes.Count];
            var indices = new int[hexes.Count];
            var source = new Tagged[hexes.Count + 2];
            source[0] = new Tagged {Id = -2, Text = "outside-left", Owner = ctx};
            source[source.Length - 1] = new Tagged {Id = -3, Text = "outside-right", Owner = ctx};
            for (int i = 0; i < hexes.Count; i++) {
                indices[i] = i;
                input[i] = Decode((string)hexes[i]);
                source[i + 1] = input[i] == null ? null : new Tagged {Id = i, Text = input[i], Owner = ctx};
            }
            var temp = new Tagged[input.Length];
            Array.Copy(source, 1, temp, 0, temp.Length);
            string error = null, inner = null, message = null;
            try {
                SortTagged(temp, ctx, back, heap);
                Array.Copy(temp, 0, source, 1, temp.Length);
            } catch (Exception ex) {
                var e = Actual(ex); error = e.GetType().FullName; message = e.Message;
                inner = e.InnerException == null ? null : e.InnerException.GetType().FullName;
            }
            object direct = ctx.Mode == "culture" && ctx.ThrowAt == 0 ? Direct(input, back, heap) : null;
            results.Add(new { name = (string)plan["name"], direction = plan["direction"],
                mode = ctx.Mode, algorithm = plan["algorithm"], count = temp.Length, capacity = temp.Length,
                throw_at = ctx.ThrowAt, throw_kind = ctx.ThrowKind, inputs_utf16le_hex = hexes,
                original_index = indices,
                order = Array.ConvertAll(temp, Id),
                temporary_utf16le_hex = Array.ConvertAll(temp, v => v == null ? null : Hex(v.Text)),
                source_order = Array.ConvertAll(source, Id),
                calls = ctx.Calls, exception = error, inner_exception = inner, message = message,
                traced_route = back ? "Array.Sort<Tagged>(Comparison reversed)" : "Array.Sort<Tagged>()",
                trace_helper_type = Helper(typeof(Tagged), !back).FullName,
                selected_default_helper = SelectedDefaultHelper(typeof(Tagged)),
                direct_string = direct,
                list_comparison = !heap && Array.IndexOf(input, null) < 0 ? ListRoute(input, back, ctx) : null });
        }
        var nls = CultureInfo.CurrentCulture.CompareInfo.Version;
        string mscorlib = typeof(object).Assembly.Location;
        using (var registry = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full")) {
            var report = new { schema = "r50-framework-arraysort-1", culture = "ja-JP", compare_options = "None",
                target_framework = ".NETFramework,Version=v4.8", effective_target = AppDomain.CurrentDomain.SetupInformation.TargetFrameworkName,
                clr = Environment.Version.ToString(), os = Environment.OSVersion.VersionString,
                process_bits = IntPtr.Size * 8,
                // Environment.OSVersion is manifest-sensitive on Framework.
                windows_registry_build = Registry.GetValue(@"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows NT\CurrentVersion", "CurrentBuildNumber", null),
                windows_registry_ubr = Registry.GetValue(@"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows NT\CurrentVersion", "UBR", null),
                framework_release = registry.GetValue("Release"), framework_version = registry.GetValue("Version"),
                framework_file_version = FileVersionInfo.GetVersionInfo(mscorlib).FileVersion,
                mscorlib_sha256 = Hash(mscorlib), probe_exe_sha256 = Hash(Assembly.GetExecutingAssembly().Location),
                plans_sha256 = Hash(args[0]), nls_version = nls.FullVersion, nls_sort_id = nls.SortId.ToString(),
                string_default_helper_type = SelectedDefaultHelper(typeof(string)),
                trace_scope = "Tagged reference IComparable<T> trace; real string[] independently measured for culture/no injection. Null identity is -1; ambiguous empty string identity -4. This is not an Emuera ERB observation.",
                cases = results };
            File.WriteAllText(args[1], serializer.Serialize(report), new UTF8Encoding(false));
        }
        Console.WriteLine("Framework arraysort cases=" + results.Count);
        return 0;
    }
}
