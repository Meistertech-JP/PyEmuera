using System;using System.IO;using System.Text;using System.Globalization;using System.Collections.Generic;
class P{static string D(string h){var b=new byte[h.Length/2];for(int i=0;i<b.Length;i++)b[i]=Convert.ToByte(h.Substring(i*2,2),16);return Encoding.Unicode.GetString(b);}
static int S(int v){return v<0?-1:(v>0?1:0);}
static void Main(string[] a){var L=File.ReadAllLines(a[0]);var o=new StringBuilder();o.Append("{\"CLR\":\""+Environment.Version+"\",\"culture\":\""+CultureInfo.CurrentCulture.Name+"\",\"pairs\":[");bool f=true;
for(int i=0;i<L.Length;i++)for(int j=0;j<L.Length;j++){string x=D(L[i]),y=D(L[j]);if(!f)o.Append(",");f=false;o.Append("{\"l\":"+i+",\"r\":"+j+",\"CompareTo\":"+S(x.CompareTo(y))+",\"CompareInfo\":"+S(CultureInfo.CurrentCulture.CompareInfo.Compare(x,y,CompareOptions.None))+"}");}
o.Append("]}");File.WriteAllText(a[1],o.ToString());}}
