// Independent Windows Framework probe; not required by the Python engine.
// Compile with Framework64/v4.0.30319/csc.exe, run with output JSON path.
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
    public static int Main(string[] args) {
        if(args.Length<1 || args.Length>2) {
            Console.Error.WriteLine("windows_collation_probe_r42.exe OUTPUT_JSON [CULTURE]");return 2;
        }
        string culture=args.Length==2?args[1]:"ja-JP";
        Thread.CurrentThread.CurrentCulture=new CultureInfo(culture);
        var input=new List<string>(new string[] {
            "a","A","あ","ア","ｱ","Ａ","１","1","ば","は\u3099","ぱ","は\u309a",
            "é","e\u0301","e","\ud83d\ude00","\ud801\udc00","Z","z","！","!","ß","ss","ü","u\u0308",
            "","\0","a\0b","ab","co-op","coop","co'op","a-b","ab-","-ab","a b",
            "å","a\u030a","Å","æ","AE","œ","oe","I","i","İ","ı","Œ","Æ",
            "ゃ","ャ","ｬ","や","ヤ","ﾔ","あゝ","ああ","カヽ","かゝ","カヾ","が",
            "アー","ｱｰ","かー","ｶｰ","ー","\u3099","\u309a","\uff9e","\uff9f",
            "亜","阿","愛","一","々","￥","\\","¥","\u00ad","\u200b",
            "\ud800","\udc00","\ud800A","A\udc00","\udbff\udfff","\ufffd","\uffff","\ud83d\ude01"
        });
        var pairs=new List<object>();
        for(int i=0;i<input.Count;i++)for(int j=i;j<input.Count;j++) {
            string left=input[i],right=input[j];
            int raw=CompareStringEx(culture,FrameworkNoneFlags,left,left.Length,right,right.Length,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero);
            int nlsError=raw==0?Marshal.GetLastWin32Error():0;
            pairs.Add(Obj("left_index",i,"right_index",j,"left_utf16le_hex",Hex(left),"right_utf16le_hex",Hex(right),
                "CompareTo_sign",Math.Sign(left.CompareTo(right)),
                "CompareInfo_None_sign",Math.Sign(CultureInfo.CurrentCulture.CompareInfo.Compare(left,right,CompareOptions.None)),
                "NLS_sign",raw==0?(object)null:raw-2,"NLS_error",nlsError));
        }
        var sorts=new List<object>();
        foreach(int length in new int[]{0,1,2,3,4,15,16,17,23,24,25,31,32,33,65}) {
            var keys=new List<KeyValuePair<string,int>>();
            for(int i=0;i<length;i++)keys.Add(new KeyValuePair<string,int>(input[i%25],i+1));
            int capacity=keys.Capacity;keys.Sort((a,b)=>a.Key.CompareTo(b.Key));
            var order=new List<int>();var values=new List<string>();
            foreach(var x in keys){order.Add(x.Value);values.Add(Hex(x.Key));}
            sorts.Add(Obj("length",length,"capacity",capacity,"permutation",order,"keys_utf16le_hex",values));
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
            "NLS_effective_id",nls.effectiveId,"NLS_sort_GUID",nls.customVersion.ToString(),
            "NLS_version_error",versionError);
        var utf16=new List<string>();foreach(string s in input)utf16.Add(Hex(s));
        var report=Obj("schema","r42-independent-framework-nls-probe-1","identity",identity,
            "inputs_utf16le_hex",utf16,"comparisons",pairs,"sorts",sorts,
            "scope","One observed OS/Framework runtime/culture. Does not prove other environments.");
        System.IO.File.WriteAllText(args[0],Json(report)+"\n",new UTF8Encoding(false));
        Console.WriteLine("inputs="+input.Count+" pairs="+pairs.Count+" sorts="+sorts.Count);return 0;
    }
}
