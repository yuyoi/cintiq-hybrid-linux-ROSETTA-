// Prints where the focused text box is ("1 left top right bottom", screen pixels) or "0", every time that changes.
// pen_injector.py reads it to pop the tablet's own keyboard up and down. It is built on first run by pen_injector.py
// with the C# compiler that ships with Windows (.NET Framework 4), so no binary is kept in the repo.
using System;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Automation;

class FocusWatch {
    [DllImport("user32.dll")] static extern bool SetProcessDpiAwarenessContext(IntPtr v);

    static bool Editable(AutomationElement e) {
        AutomationElement.AutomationElementInformation c = e.Current;
        object p;
        bool val = e.TryGetCurrentPattern(ValuePattern.Pattern, out p);
        if (val && ((ValuePattern)p).Current.IsReadOnly) return false;          // a web page, a label, a read-only box
        if (c.ControlType == ControlType.Edit) return true;
        if (c.ControlType == ControlType.Document || c.ControlType == ControlType.ComboBox) return val;   // writable ones only
        return false;
    }

    static void Main(string[] args) {
        try { SetProcessDpiAwarenessContext(new IntPtr(-4)); } catch { }             // real pixels, like the injector
        System.Diagnostics.Process parent = null;                                     // quit together with the injector
        if (args.Length > 0) try { parent = System.Diagnostics.Process.GetProcessById(int.Parse(args[0])); } catch { return; }
        string last = null;
        while (true) {
            if (parent != null && parent.HasExited) return;
            string s = "0";
            try {
                AutomationElement e = AutomationElement.FocusedElement;
                if (e != null && Editable(e)) {
                    System.Windows.Rect r = e.Current.BoundingRectangle;
                    if (!r.IsEmpty) s = string.Format("1 {0} {1} {2} {3}", (int)r.Left, (int)r.Top, (int)r.Right, (int)r.Bottom);
                }
            } catch { s = last ?? "0"; }                                               // the focused app was busy
            if (s != last) {
                try { Console.WriteLine(s); Console.Out.Flush(); } catch { return; }       // the reader is gone
                last = s;
            }
            Thread.Sleep(150);
        }
    }
}
