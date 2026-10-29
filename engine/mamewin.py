"""Start MAME out of the user's way: never a window in front of the user, never the focus or the keyboard (every
script that starts MAME with a window uses this; a MAME started with -video none opens none and needs nothing).

    import mamewin
    r = mamewin.run([exe, game, "-window", ...], cwd=d, check=True, stdout=subprocess.DEVNULL)   # as subprocess.run
    p = mamewin.popen([exe, game, ...], stdout=subprocess.PIPE)                               # as subprocess.Popen

On Windows MAME runs on a desktop of its own (CreateDesktop, "STEArcadeMAME" in the user's window station): its
windows exist and draw, but on a desktop nobody looks at, so they can neither show up nor take the foreground (a
minimized MAME still did: it shows its window with SW_SHOW and moves it without SWP_NOACTIVATE, and once nobody has
typed for a while Windows lets any process take the foreground).  The window is also started minimized, and MAME
draws through GDI there (-video gdi unless the call names a -video: Direct3D and bgfx crash on such a desktop).  Snapshots,
-aviwrite and -wavwrite come from the emulation, not the screen, so they are the same.  Python's subprocess has no
lpDesktop, so Popen's CreateProcess is replaced, for these calls only, by CreateProcessW through ctypes (the same
handles, the same handle list).  Elsewhere both are plain subprocess calls.
"""
import os
import subprocess
import threading

DESKTOP = "STEArcadeMAME"
SW_SHOWMINNOACTIVE = 7
_lock = threading.Lock()
_desktop = None                  # (the handle stays open: the desktop lives as long as a handle to it does)


class _HiddenStartup(subprocess.STARTUPINFO if os.name == "nt" else object):
    """A STARTUPINFO that marks a MAME start for the CreateProcess replacement (Popen copies it: so does copy)."""

    def copy(self):
        c = super().copy()
        return _HiddenStartup(dwFlags=c.dwFlags, hStdInput=c.hStdInput, hStdOutput=c.hStdOutput,
                              hStdError=c.hStdError, wShowWindow=c.wShowWindow, lpAttributeList=c.lpAttributeList)


def _ensure_desktop():
    global _desktop
    import ctypes
    from ctypes import wintypes
    with _lock:
        if _desktop is None:
            u = ctypes.windll.user32
            u.CreateDesktopW.restype = wintypes.HANDLE
            u.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD,
                                         wintypes.DWORD, ctypes.c_void_p]
            h = u.CreateDesktopW(DESKTOP, None, None, 0, 0x10000000, None)      # GENERIC_ALL
            if not h:
                raise ctypes.WinError()
            _desktop = h
            _install()


def _install():
    """Wrap subprocess._winapi.CreateProcess once: a call with a _HiddenStartup goes through CreateProcessW with
    lpDesktop; every other call is passed on unchanged."""
    import _winapi
    import ctypes
    from ctypes import wintypes
    original = subprocess._winapi.CreateProcess
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                    ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                    ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                    ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                    ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
                    ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]

    class STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE), ("dwProcessId", wintypes.DWORD),
                    ("dwThreadId", wintypes.DWORD)]

    k32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL,
                                   wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_void_p,
                                   ctypes.POINTER(PROCESS_INFORMATION)]
    k32.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                                      ctypes.POINTER(ctypes.c_size_t)]
    k32.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p,
                                              ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
    k32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]

    def create(app, cmd, pattr, tattr, inherit, flags, env, cwd, si):
        if not isinstance(si, _HiddenStartup):
            return original(app, cmd, pattr, tattr, inherit, flags, env, cwd, si)
        s = STARTUPINFOEXW()
        s.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)                         # (with the attribute list)
        desk = ctypes.create_unicode_buffer("WinSta0\\" + DESKTOP)
        s.StartupInfo.lpDesktop = ctypes.cast(desk, wintypes.LPWSTR)
        s.StartupInfo.dwFlags = si.dwFlags
        s.StartupInfo.wShowWindow = si.wShowWindow
        s.StartupInfo.hStdInput, s.StartupInfo.hStdOutput, s.StartupInfo.hStdError = (
            int(h) if h not in (None, -1) else None for h in (si.hStdInput, si.hStdOutput, si.hStdError))
        handles = list((si.lpAttributeList or {}).get("handle_list", ()))
        attrs = None
        if handles:
            size = ctypes.c_size_t()
            k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
            attrs = ctypes.create_string_buffer(size.value)
            if not k32.InitializeProcThreadAttributeList(attrs, 1, 0, ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            harr = (wintypes.HANDLE * len(handles))(*handles)
            if not k32.UpdateProcThreadAttribute(attrs, 0, 0x20002, harr, ctypes.sizeof(harr), None, None):
                raise ctypes.WinError(ctypes.get_last_error())                 # PROC_THREAD_ATTRIBUTE_HANDLE_LIST
            s.lpAttributeList = ctypes.cast(attrs, ctypes.c_void_p)
            flags |= 0x00080000                                                  # EXTENDED_STARTUPINFO_PRESENT
        block = None
        if env is not None:
            flags |= 0x00000400                                                  # CREATE_UNICODE_ENVIRONMENT
            block = ctypes.create_unicode_buffer("".join("%s=%s\0" % kv for kv in env.items()) + "\0")
        pi = PROCESS_INFORMATION()
        cmdbuf = ctypes.create_unicode_buffer(cmd)
        try:
            ok = k32.CreateProcessW(app, cmdbuf, None, None, bool(inherit), flags, block, cwd,
                                    ctypes.byref(s), ctypes.byref(pi))
            if not ok:
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            if attrs is not None:
                k32.DeleteProcThreadAttributeList(attrs)
        return pi.hProcess, pi.hThread, pi.dwProcessId, pi.dwThreadId

    subprocess._winapi = type("winapi", (), {"__getattr__": lambda self, n: getattr(_winapi, n)})()
    subprocess._winapi.CreateProcess = create


def popen(args, **kw):
    """subprocess.Popen on MAME's own desktop (Windows), started minimized."""
    if os.name != "nt":
        return subprocess.Popen(args, **kw)
    _ensure_desktop()
    if "-video" not in args:
        args = list(args) + ["-video", "gdi"]       # (d3d and bgfx crash on a desktop nobody shows; gdi draws there)
    si = _HiddenStartup()
    old = kw.pop("startupinfo", None)
    if old is not None:
        si.dwFlags, si.wShowWindow = old.dwFlags, old.wShowWindow
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = SW_SHOWMINNOACTIVE
    return subprocess.Popen(args, startupinfo=si, **kw)


def run(args, timeout=None, check=False, capture_output=False, input=None, **kw):
    """subprocess.run on MAME's own desktop (Windows)."""
    if capture_output:
        kw["stdout"] = kw["stderr"] = subprocess.PIPE
    if input is not None:
        kw["stdin"] = subprocess.PIPE
    with popen(args, **kw) as p:
        try:
            out, err = p.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
            raise
    if check and p.returncode:
        raise subprocess.CalledProcessError(p.returncode, args, out, err)
    return subprocess.CompletedProcess(args, p.returncode, out, err)
