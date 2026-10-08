# usage: hkey.ps1 <pid> <action>   action: grab | down:<vk> | up:<vk> | tap:<vk>
param([int]$ProcId, [string]$Action)
Add-Type @"
using System; using System.Text; using System.Collections.Generic; using System.Runtime.InteropServices;
public class K {
 public delegate bool EnumProc(IntPtr h, IntPtr l);
 [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc p, IntPtr l);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
 public static IntPtr FindSdl(uint pid) {
   IntPtr r = IntPtr.Zero;
   EnumWindows((h,l)=>{ uint p; GetWindowThreadProcessId(h, out p); if (p==pid && IsWindowVisible(h)) { var sb=new StringBuilder(256); GetClassName(h,sb,256); if (sb.ToString().StartsWith("SDL")) r=h; } return true; }, IntPtr.Zero);
   return r;
 }
}
"@
$h = [K]::FindSdl([uint32]$ProcId)
if ($h -eq [IntPtr]::Zero) { "no window"; exit }
[K]::SetForegroundWindow($h) | Out-Null
Start-Sleep -Milliseconds 300
function Tap($vk) { [K]::keybd_event($vk,0,0,[UIntPtr]::Zero); Start-Sleep -Milliseconds 60; [K]::keybd_event($vk,0,2,[UIntPtr]::Zero); Start-Sleep -Milliseconds 60 }
if ($Action -eq "grab") {
  [K]::keybd_event(0xA5,0,1,[UIntPtr]::Zero)      # right alt (AltGr) down, extended
  Start-Sleep -Milliseconds 80
  Tap 0x47                                        # G
  [K]::keybd_event(0xA5,0,3,[UIntPtr]::Zero)      # up
  "grab sent"
} elseif ($Action -like "tap:*") {
  Tap ([int]($Action.Substring(4)))
  "tap sent"
}
