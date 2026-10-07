# usage: shot.ps1 <pid> <out.png>  -- capture the SDL window of a Hatari process
param([int]$ProcId, [string]$Out)
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Text; using System.Collections.Generic; using System.Runtime.InteropServices;
public class W2 {
 public delegate bool EnumProc(IntPtr h, IntPtr l);
 [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc p, IntPtr l);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
 [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
 [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
 [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
 [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
 [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X,Y; }
 public static List<IntPtr> Find(uint pid) {
   var res = new List<IntPtr>();
   EnumWindows((h,l)=>{ uint p; GetWindowThreadProcessId(h, out p); if (p==pid && IsWindowVisible(h)) res.Add(h); return true; }, IntPtr.Zero);
   return res;
 }
 public static string Cls(IntPtr h){ var sb=new StringBuilder(256); GetClassName(h,sb,256); return sb.ToString(); }
}
"@
$wins = [W2]::Find([uint32]$ProcId)
foreach ($h in $wins) {
  $cls = [W2]::Cls($h)
  if ($cls -like "SDL*") {
    $r = New-Object W2+RECT
    [W2]::GetClientRect($h, [ref]$r) | Out-Null
    $pt = New-Object W2+POINT
    [W2]::ClientToScreen($h, [ref]$pt) | Out-Null
    $w = $r.R; $hh = $r.B
    $bmp = New-Object System.Drawing.Bitmap $w,$hh
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    [W2]::ShowWindow($h, 9) | Out-Null
    [W2]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero)
    [W2]::SetForegroundWindow($h) | Out-Null
    [W2]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 900
    $g.CopyFromScreen($pt.X, $pt.Y, 0, 0, (New-Object System.Drawing.Size($w,$hh)))
    $bmp.Save($Out)
    "captured $cls ${w}x${hh}"
    exit
  }
}
"no SDL window; windows: " + (($wins | ForEach-Object { [W2]::Cls($_) }) -join ",")
