// r43 independent Framework/NLS probe; no native result has been produced here.
// Compile with Framework64/v4.0.30319/csc.exe.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Text;
using System.Threading;
[assembly: TargetFramework(".NETFramework,Version=v4.8")]
public static class CollationProbe {
    const uint FrameworkNoneFlags = 0x08000000;
    [StructLayout(LayoutKind.Sequential)] public struct NlsVersion {
        public uint size, version, definedVersion, effectiveId;
        public Guid customVersion;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern int CompareStringEx(string locale, uint flags, string a, int aLength,
        string b, int bLength, IntPtr version, IntPtr reserved, IntPtr parameter);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern bool GetNLSVersionEx(int function, string locale, ref NlsVersion version);
    static Dictionary<string,object> Obj(params object[] args) {
        var d=new Dictionary<string,object>();
        for(int i=0;i<args.Length;i+=2)d[(string)args[i]]=args[i+1];
        return d;
    }
    static string Quote(string s) {
        var b=new StringBuilder("\"");
        // Every UTF16 unit is escaped, including unpaired surrogates/NUL.
        foreach(char c in s)b.Append("\\u").Append(((int)c).ToString("x4",CultureInfo.InvariantCulture));
        return b.Append('"').ToString();
    }
    static string Json(object value) {
        if(value==null)return "null";
        if(value is string)return Quote((string)value);
        if(value is bool)return (bool)value?"true":"false";
        if(value is IDictionary) {
            var parts=new List<string>();
            foreach(DictionaryEntry e in (IDictionary)value)parts.Add(Quote((string)e.Key)+":"+Json(e.Value));
            return "{"+String.Join(",",parts.ToArray())+"}";
        }
        if(value is IEnumerable) {
            var parts=new List<string>();foreach(object x in (IEnumerable)value)parts.Add(Json(x));
            return "["+String.Join(",",parts.ToArray())+"]";
        }
        return Convert.ToString(value,CultureInfo.InvariantCulture);
    }
    static string Hex(string text) {
        var b=new StringBuilder();
        foreach(char c in text) {
            b.Append(((int)c&255).ToString("x2",CultureInfo.InvariantCulture));
            b.Append(((int)c>>8).ToString("x2",CultureInfo.InvariantCulture));
        }
        return b.ToString();
    }
    static string DecodeHex(string hex) {
        if(hex.Length%4!=0)throw new ArgumentException("UTF16 hex must contain complete code units");
        var chars=new char[hex.Length/4];
        for(int i=0;i<chars.Length;i++) {
            int low=Int32.Parse(hex.Substring(i*4,2),NumberStyles.HexNumber,CultureInfo.InvariantCulture);
            int high=Int32.Parse(hex.Substring(i*4+2,2),NumberStyles.HexNumber,CultureInfo.InvariantCulture);
            chars[i]=(char)(low|(high<<8));
        }
        return new string(chars); // Preserves lone surrogates; no decoder replacement.
    }
    static string FileHash(string path) {
        using(var h=System.Security.Cryptography.SHA256.Create()) {
            var bytes=h.ComputeHash(System.IO.File.ReadAllBytes(path));
            return BitConverter.ToString(bytes).Replace("-","").ToLowerInvariant();
        }
    }
    public static int Main(string[] args) {
        if(args.Length<4 || args.Length>5) {
            Console.Error.WriteLine("windows_collation_probe_r43.exe INPUT_HEX PAIRS_TSV SORT_ORDERS_TSV OUTPUT_JSON [CULTURE]");return 2;
        }
        string culture=args.Length==5?args[4]:"ja-JP";
        Thread.CurrentThread.CurrentCulture=new CultureInfo(culture);
        var input=new List<string>();var utf16=new List<string>();
        foreach(string hex in System.IO.File.ReadAllLines(args[0])) {
            string s=DecodeHex(hex);input.Add(s);utf16.Add(Hex(s));
        }
        var pairs=new List<object>();
        foreach(string line in System.IO.File.ReadAllLines(args[1])) {
            var fields=line.Split('\t');
            int i=Int32.Parse(fields[0],CultureInfo.InvariantCulture),j=Int32.Parse(fields[1],CultureInfo.InvariantCulture);
            string left=input[i],right=input[j];
            int raw=CompareStringEx(culture,FrameworkNoneFlags,left,left.Length,right,right.Length,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero);
            int nlsError=raw==0?Marshal.GetLastWin32Error():0;
            pairs.Add(Obj("left_index",i,"right_index",j,"left_utf16le_hex",Hex(left),"right_utf16le_hex",Hex(right),
                "CompareTo_sign",Math.Sign(left.CompareTo(right)),
                "CompareInfo_None_sign",Math.Sign(CultureInfo.CurrentCulture.CompareInfo.Compare(left,right,CompareOptions.None)),
                "NLS_sign",raw==0?(object)null:raw-2,"NLS_error",nlsError));
        }
        var sorts=new List<object>();
        foreach(string line in System.IO.File.ReadAllLines(args[2])) {
            var fields=line.Split('\t');var sources=fields[1].Split(',');
            var keys=new List<KeyValuePair<string,int>>();var inputIndices=new List<int>();
            for(int i=0;i<sources.Length;i++) {
                int index=Int32.Parse(sources[i],CultureInfo.InvariantCulture);inputIndices.Add(index);
                keys.Add(new KeyValuePair<string,int>(input[index],i+1));
            }
            int capacity=keys.Capacity;keys.Sort((a,b)=>a.Key.CompareTo(b.Key));
            var order=new List<int>();var values=new List<string>();
            foreach(var x in keys){order.Add(x.Value);values.Add(Hex(x.Key));}
            sorts.Add(Obj("case_id",fields[0],"input_indices",inputIndices,"length",sources.Length,"capacity",capacity,"permutation",order,"keys_utf16le_hex",values));
        }
        NlsVersion nls=new NlsVersion();nls.size=(uint)Marshal.SizeOf(typeof(NlsVersion));
        bool versionOk=GetNLSVersionEx(1,culture,ref nls);
        int versionError=versionOk?0:Marshal.GetLastWin32Error();
        var identity=Obj("CurrentCulture",CultureInfo.CurrentCulture.Name,"CurrentUICulture",CultureInfo.CurrentUICulture.Name,
            "CompareOptions","None","NLS_flags",FrameworkNoneFlags,"CLR",Environment.Version.ToString(),
            "TargetFramework",".NETFramework,Version=v4.8","OS_version_reported",Environment.OSVersion.Version.ToString(),
            "mscorlib_file",typeof(string).Assembly.Location,"mscorlib_assembly",typeof(string).Assembly.FullName,
            "mscorlib_file_version",System.Diagnostics.FileVersionInfo.GetVersionInfo(typeof(string).Assembly.Location).FileVersion,
            "Framework_release",Microsoft.Win32.Registry.GetValue(@"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full","Release",null),
            "OS_registry_build",Microsoft.Win32.Registry.GetValue(@"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows NT\CurrentVersion","CurrentBuildNumber",null),
            "NLS_version_success",versionOk,"NLS_version",nls.version,"NLS_defined_version",nls.definedVersion,
            "NLS_effective_id",nls.effectiveId,"NLS_sort_GUID",nls.customVersion.ToString(),"NLS_version_error",versionError);
        var report=Obj("schema","r43-independent-framework-nls-probe-1","identity",identity,
            "inputs_sha256",FileHash(args[0]),"pair_plan_sha256",FileHash(args[1]),"sort_plan_sha256",FileHash(args[2]),
            "inputs_utf16le_hex",utf16,"comparisons",pairs,"sorts",sorts,
            "scope","New observations only when this compiled probe is actually executed on the recorded Windows host.");
        System.IO.File.WriteAllText(args[3],Json(report)+"\n",new UTF8Encoding(false));
        Console.WriteLine("inputs="+input.Count+" pairs="+pairs.Count+" sorts="+sorts.Count);return 0;
    }
}
