# Creates a Start Menu shortcut "Transcript History" that opens the live
# transcript browser as its own app (searchable in Start, pinnable to taskbar).
# The shortcut's AppUserModelID must match APP_ID in
# src/whisper_key/history_window.py so the taskbar shows our name + icon, not "Python".
# Re-run after moving the repo folder.

$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$pythonw = Join-Path $repo '.venv\Scripts\pythonw.exe'
$icon = Join-Path $repo 'src\whisper_key\platform\windows\assets\whisperkey-icon.ico'
$lnk = Join-Path ([Environment]::GetFolderPath('Programs')) 'Transcript History.lnk'
$appId = 'WhisperLocal.TranscriptHistory'

if (-not (Test-Path $pythonw)) { throw "venv not found: $pythonw" }

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

[ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IShellLinkW {
    void GetPath(IntPtr f, int cch, IntPtr fd, uint flags);
    void GetIDList(out IntPtr ppidl);
    void SetIDList(IntPtr pidl);
    void GetDescription(IntPtr s, int cch);
    void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string s);
    void GetWorkingDirectory(IntPtr s, int cch);
    void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string s);
    void GetArguments(IntPtr s, int cch);
    void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string s);
    void GetHotkey(out short h);
    void SetHotkey(short h);
    void GetShowCmd(out int c);
    void SetShowCmd(int c);
    void GetIconLocation(IntPtr s, int cch, out int i);
    void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string s, int i);
    void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string s, uint r);
    void Resolve(IntPtr hwnd, uint flags);
    void SetPath([MarshalAs(UnmanagedType.LPWStr)] string s);
}

[StructLayout(LayoutKind.Sequential, Pack = 4)]
struct PropertyKey { public Guid fmtid; public uint pid; }

[StructLayout(LayoutKind.Explicit, Size = 24)]
struct PropVariant { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr ptr; }

[ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPropertyStore {
    void GetCount(out uint c);
    void GetAt(uint i, out PropertyKey k);
    void GetValue(ref PropertyKey k, out PropVariant v);
    void SetValue(ref PropertyKey k, ref PropVariant v);
    void Commit();
}

public static class HistoryShortcut {
    public static void Create(string lnk, string target, string args, string workDir, string icon, string appId, string desc) {
        var link = (IShellLinkW)Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("00021401-0000-0000-C000-000000000046")));
        link.SetPath(target);
        link.SetArguments(args);
        link.SetWorkingDirectory(workDir);
        link.SetIconLocation(icon, 0);
        link.SetDescription(desc);

        // System.AppUserModel.ID
        var key = new PropertyKey { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
        var pv = new PropVariant { vt = 31 /* VT_LPWSTR */, ptr = Marshal.StringToCoTaskMemUni(appId) };
        try {
            var store = (IPropertyStore)link;
            store.SetValue(ref key, ref pv);
            store.Commit();
        } finally {
            Marshal.FreeCoTaskMem(pv.ptr);
        }
        ((IPersistFile)link).Save(lnk, true);
    }
}
'@

[HistoryShortcut]::Create($lnk, $pythonw, '-m whisper_key.main --history', $repo, $icon, $appId,
    'Browse and search your Whisper Local dictations (updates live)')
Write-Output "Created: $lnk"
