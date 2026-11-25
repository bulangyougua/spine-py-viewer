param([Parameter(Mandatory = $true)][int]$ProcessId)

$source = @'
using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

public sealed class NativeDropTarget : IOleDropTarget
{
    private readonly IntPtr window;

    private NativeDropTarget(IntPtr window)
    {
        this.window = window;
    }

    public static void Attach(int processId)
    {
        IntPtr window = IntPtr.Zero;
        for (int attempt = 0; attempt < 200 && window == IntPtr.Zero; attempt++)
        {
            EnumWindows(delegate(IntPtr candidate, IntPtr parameter)
            {
                StringBuilder title = new StringBuilder(256);
                GetWindowText(candidate, title, title.Capacity);
                StringBuilder className = new StringBuilder(128);
                GetClassName(candidate, className, className.Capacity);
                if (IsWindowVisible(candidate) && title.ToString() == "Spine 动画查看器" &&
                    className.ToString().StartsWith("Chrome_WidgetWin_"))
                {
                    window = candidate;
                    return false;
                }
                return true;
            }, IntPtr.Zero);
            if (window == IntPtr.Zero) Thread.Sleep(100);
        }
        if (window == IntPtr.Zero) throw new InvalidOperationException("Browser window not found");
        int oleResult = OleInitialize(IntPtr.Zero);
        if (oleResult != 0 && oleResult != 1) throw new InvalidOperationException("OleInitialize failed: 0x" + oleResult.ToString("X8"));
        RevokeDragDrop(window);
        int result = RegisterDragDrop(window, new NativeDropTarget(window));
        if (result != 0) throw new InvalidOperationException("RegisterDragDrop failed: 0x" + result.ToString("X8"));
        uint browserPid;
        GetWindowThreadProcessId(window, out browserPid);
        Console.WriteLine("READY " + browserPid);
        Console.Out.Flush();
        while (IsWindow(window))
        {
            Application.DoEvents();
            Thread.Sleep(50);
        }
        RevokeDragDrop(window);
        OleUninitialize();
    }

    public int DragEnter(object data, int keyState, PointL point, ref uint effect)
    {
        effect = HasFiles(data) ? 1u : 0u; // DROPEFFECT_COPY
        return 0;
    }

    public int DragOver(int keyState, PointL point, ref uint effect)
    {
        return 0;
    }

    public int DragLeave()
    {
        return 0;
    }

    public int Drop(object data, int keyState, PointL point, ref uint effect)
    {
        if (!HasFiles(data)) { effect = 0; return 0; }
        string[] paths = (string[])new DataObject(data).GetData(DataFormats.FileDrop);
        foreach (string path in paths)
        {
            Console.WriteLine(Convert.ToBase64String(Encoding.UTF8.GetBytes(path)));
        }
        Console.Out.Flush();
        effect = 1;
        return 0;
    }

    private static bool HasFiles(object data)
    {
        return new DataObject(data).GetDataPresent(DataFormats.FileDrop);
    }

    private delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr parameter);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr parameter);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hwnd);

    [DllImport("user32.dll")]
    private static extern bool IsWindow(IntPtr hwnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int count);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetClassName(IntPtr hwnd, StringBuilder text, int count);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);

    [DllImport("ole32.dll")]
    private static extern int OleInitialize(IntPtr reserved);

    [DllImport("ole32.dll")]
    private static extern void OleUninitialize();

    [DllImport("ole32.dll")]
    private static extern int RegisterDragDrop(IntPtr hwnd, IOleDropTarget target);

    [DllImport("ole32.dll")]
    private static extern int RevokeDragDrop(IntPtr hwnd);
}

[ComImport]
[Guid("00000122-0000-0000-C000-000000000046")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IOleDropTarget
{
    [PreserveSig]
    int DragEnter([MarshalAs(UnmanagedType.Interface)] object data, int keyState, PointL point, ref uint effect);
    [PreserveSig]
    int DragOver(int keyState, PointL point, ref uint effect);
    [PreserveSig]
    int DragLeave();
    [PreserveSig]
    int Drop([MarshalAs(UnmanagedType.Interface)] object data, int keyState, PointL point, ref uint effect);
}

[StructLayout(LayoutKind.Sequential)]
public struct PointL
{
    public int x;
    public int y;
}
'@

try {
    $null = [Console]::InputEncoding
    [Console]::InputEncoding = [System.Text.Encoding]::UTF8
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    Add-Type -TypeDefinition $source -ReferencedAssemblies System.Windows.Forms -ErrorAction Stop
    [NativeDropTarget]::Attach($ProcessId)
} catch {
    [Console]::Error.WriteLine($_.Exception.ToString())
    exit 1
}
