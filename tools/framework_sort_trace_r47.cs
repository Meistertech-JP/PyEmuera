// Target-framework quirks are part of the oracle contract. Compile both ways.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.Versioning;
using System.Threading;
using System.Web.Script.Serialization;
#if R47_MODERN
[assembly: TargetFramework(".NETFramework,Version=v4.8")]
#endif

public static class FrameworkSortTraceR47 {
 static string Decode(string hex) {
  char[] chars = new char[hex.Length/4];
  for (int i=0;i<chars.Length;i++) chars[i]=(char)(int.Parse(hex.Substring(i*4,2),NumberStyles.HexNumber)|int.Parse(hex.Substring(i*4+2,2),NumberStyles.HexNumber)<<8);
  return new string(chars);
 }
 public static int Main(string[] args) {
  Thread.CurrentThread.CurrentCulture=new CultureInfo("ja-JP");
  Thread.CurrentThread.CurrentUICulture=new CultureInfo("ja-JP");
  var serializer=new JavaScriptSerializer(); serializer.MaxJsonLength=int.MaxValue;
  var plans=serializer.Deserialize<List<Dictionary<string,object>>>(File.ReadAllText(args[0]));
  var results=new List<object>();
  foreach(var plan in plans) {
   var hexes=(System.Collections.ArrayList)plan["inputs_utf16le_hex"];
   string mode=(string)plan["mode"];
   var items=new List<KeyValuePair<string,int>>();
   for(int i=0;i<hexes.Count;i++) items.Add(new KeyValuePair<string,int>(Decode((string)hexes[i]),i));
   var calls=new List<object>();
   Comparison<KeyValuePair<string,int>> compare=(left,right)=>{
    int sign;
    if(mode=="culture") sign=Math.Sign(left.Key.CompareTo(right.Key));
    else if(mode=="ordinal") sign=Math.Sign(StringComparer.Ordinal.Compare(left.Key,right.Key));
    else sign=left.Value==right.Value?0:-1;
    calls.Add(new {call_index=calls.Count,left_original_row=left.Value,right_original_row=right.Value,comparison_sign=sign});
    return sign;
   };
   string error=null, message=null;
   try {items.Sort(compare);} catch(Exception e) {error=e.GetType().FullName;message=e.Message;}
   var order=new List<int>();foreach(var row in items)order.Add(row.Value);
   results.Add(new {name=(string)plan["name"],mode=mode,count=items.Count,capacity=items.Capacity,
    list_type=items.GetType().FullName,comparer_type="System.Array+FunctorComparer<KeyValuePair<string,int>>",
    exception=error,message=message,order=order,calls=calls});
  }
  var attr=(TargetFrameworkAttribute)Attribute.GetCustomAttribute(Assembly.GetExecutingAssembly(),typeof(TargetFrameworkAttribute));
  var report=new {schema="r47-framework-sort-trace-1",target_framework=attr==null?null:attr.FrameworkName,
   effective_target=AppDomain.CurrentDomain.SetupInformation.TargetFrameworkName,clr=Environment.Version.ToString(),
   mscorlib=typeof(object).Assembly.Location,culture=Thread.CurrentThread.CurrentCulture.Name,cases=results};
  File.WriteAllText(args[1],serializer.Serialize(report),new System.Text.UTF8Encoding(false));
  Console.WriteLine("sort cases="+results.Count+" target="+(attr==null?"absent":attr.FrameworkName));
  return 0;
 }
}
