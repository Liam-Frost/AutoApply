// AutoApply setup for Windows: the window. One small program that shows the pages (install, upgrade, repair,
// remove, progress, result) in the program's own design and does none of the installing itself.
//
// The installing is done by the Inno Setup installer built from ..\autoapply.iss, which this program carries inside
// itself and runs without its wizard. They talk through three small files in a folder this program names
// (/STATUSDIR): prepare.status "<step> <percent> <part>", prepare.done "ok" | "cancelled" | "error <code>", and
// prepare.cancel, which this program creates to ask for a stop. Removing is done by the uninstaller Inno Setup
// left in the program folder.
//
// The same source is built twice (scripts/make_installer.py): without the installer inside, as AutoApplySetup.exe
// in the program folder - what Settings > Apps starts to remove the program - and with it, as the download.
//
//   AutoApply-Setup.exe                         the window
//   AutoApply-Setup.exe /VERYSILENT ...         no window: every argument goes to the Inno Setup installer as it is
//   AutoApplySetup.exe /uninstall [/dir=..]     the window, on its remove page
// For checking without clicking:
//   /auto /result=<file>     open the real window, press its main button, wait, write "<state>|<title>|<text>", close
//   /shot=<png> /page=<welcome|existing|same|running|progress|done|failed|uninstall> [/dark]   draw one page to a file
//   /dir=<folder> /lang=<zh|en> /notasks /deletedata
//
// Written for the C# compiler that is part of Windows (.NET Framework 4), so that building needs nothing installed:
// no string interpolation, no "?." and the like.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Management;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using Microsoft.Win32;

static class Program
{
    public static Dictionary<string, string> Args = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    public static int ExitCode;

    [STAThread]
    static int Main(string[] argv)
    {
        foreach (string a in argv)
        {
            if (!a.StartsWith("/")) continue;
            int eq = a.IndexOf('=');
            if (eq < 0) Args[a.Substring(1)] = ""; else Args[a.Substring(1, eq - 1)] = a.Substring(eq + 1).Trim('"');
        }
        if (Args.ContainsKey("silent") || Args.ContainsKey("verysilent")) return Silent(argv);
        bool created;
        using (Mutex one = new Mutex(true, "Local\\" + Build.AppName.Replace(" ", "") + "Setup", out created))
        {
            if (!created && !Args.ContainsKey("shot") && !Args.ContainsKey("auto"))
            {
                MessageBox.Show(Ui.Chinese() ? "AutoApply 的安装程序已经在运行了，请看任务栏。" : "AutoApply setup is already running - look at the taskbar.", Build.AppName);
                return 0;
            }
            new Ui().Run();
        }
        return ExitCode;
    }

    // No window: hand everything to the installer (or, to remove, to the uninstaller) and return what it returns.
    static int Silent(string[] argv)
    {
        List<string> pass = new List<string>();
        foreach (string a in argv)
            if (!a.StartsWith("/uninstall", StringComparison.OrdinalIgnoreCase) && !a.StartsWith("/dir=", StringComparison.OrdinalIgnoreCase)) pass.Add(Quote(a));
        if (Args.ContainsKey("uninstall"))
        {
            string dir = Args.ContainsKey("dir") ? Args["dir"] : Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
            return Engine.Wait(Path.Combine(dir, "unins000.exe"), string.Join(" ", pass.ToArray()));
        }
        if (Args.ContainsKey("dir")) pass.Add("/DIR=\"" + Args["dir"] + "\"");
        string engine = Engine.Extract();
        if (engine == null) return 2;
        try { return Engine.Wait(engine, string.Join(" ", pass.ToArray())); }
        finally { Engine.Clean(engine); }
    }

    public static string Quote(string a)
    {
        int eq = a.IndexOf('=');
        if (eq < 0 || a.IndexOf(' ') < 0 || a.IndexOf('"') >= 0) return a;
        return a.Substring(0, eq + 1) + "\"" + a.Substring(eq + 1) + "\"";
    }
}

// The Inno Setup installer carried inside this program.
static class Engine
{
    public static bool Present()
    {
        return Assembly.GetExecutingAssembly().GetManifestResourceInfo("engine.exe") != null;
    }

    public static string Extract()
    {
        using (Stream s = Assembly.GetExecutingAssembly().GetManifestResourceStream("engine.exe"))
        {
            if (s == null) return null;
            string dir = Path.Combine(Path.GetTempPath(), "AutoApplySetup-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(dir);
            string exe = Path.Combine(dir, "AutoApply-Setup-engine.exe");
            using (FileStream f = File.Create(exe)) s.CopyTo(f);
            return exe;
        }
    }

    public static void Clean(string engine)
    {
        try { Directory.Delete(Path.GetDirectoryName(engine), true); } catch (IOException) { } catch (UnauthorizedAccessException) { }
    }

    public static Process Start(string exe, string arguments)
    {
        ProcessStartInfo i = new ProcessStartInfo(exe, arguments);
        i.UseShellExecute = false;
        i.CreateNoWindow = true;
        return Process.Start(i);
    }

    public static int Wait(string exe, string arguments)
    {
        if (!File.Exists(exe)) return 2;
        using (Process p = Start(exe, arguments)) { p.WaitForExit(); return p.ExitCode; }
    }
}

class Installed
{
    public string Dir, Version;
    public bool BySetup;        // registered by a setup program (not a copy that was unzipped and started by hand)
}

class Ui
{
    const string RunKey = "Software\\Microsoft\\Windows\\CurrentVersion\\Run";
    const string Uninstall = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\";

    Window win;
    Dictionary<string, object> ui = new Dictionary<string, object>();
    Dictionary<string, string> tok;
    bool zh, removing, uninstallOnly, optsSeen, pressed, cancelAsked, cancelSent;
    string state = "choose";     // choose | remove | work | done | failed
    string target, lastError = "", statusDir, engine, langCheck = "";
    Installed inst;
    Process proc;
    DateTime began, cancelAskedAt, removeUntil;
    int step;
    DispatcherTimer timer = new DispatcherTimer();

    // --- small helpers ---

    public static bool Chinese()
    {
        if (Program.Args.ContainsKey("lang")) return Program.Args["lang"].ToLowerInvariant().StartsWith("zh");
        foreach (CultureInfo c in new CultureInfo[] { CultureInfo.CurrentUICulture, CultureInfo.CurrentCulture, CultureInfo.InstalledUICulture })
            if (c.Name.StartsWith("zh", StringComparison.OrdinalIgnoreCase)) return true;
        return false;
    }

    string T(string cn, string en) { return zh ? cn : en; }
    Brush B(string name) { return (Brush)new BrushConverter().ConvertFromString(tok[name]); }
    TextBlock Text(string n) { return (TextBlock)ui[n]; }
    Button Btn(string n) { return (Button)ui[n]; }
    FrameworkElement El(string n) { return (FrameworkElement)ui[n]; }
    ToggleButton Tog(string n) { return (ToggleButton)ui[n]; }
    static Visibility Vis(bool on) { return on ? Visibility.Visible : Visibility.Collapsed; }
    string Arg(string name) { return Program.Args.ContainsKey(name) ? Program.Args[name] : ""; }
    bool Has(string name) { return Program.Args.ContainsKey(name); }

    static string DefaultDir()
    {
        return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", Build.AppName);
    }

    static string VersionIn(string dir)
    {
        try
        {
            string f = Path.Combine(dir, "pyproject.toml");
            if (!File.Exists(f)) return null;
            Match m = Regex.Match(File.ReadAllText(f), "^version\\s*=\\s*\"([^\"]+)\"", RegexOptions.Multiline);
            return m.Success ? m.Groups[1].Value : null;
        }
        catch (IOException) { return null; }
    }

    // The copy that is installed: where Inno Setup registered it, or where versions up to 1.0.3 registered themselves.
    static Installed FindInstalled()
    {
        List<string> keys = new List<string>();
        keys.Add(Uninstall + Build.Guid + "_is1");
        if (Build.AppName == "AutoApply") keys.Add(Uninstall + "AutoApply");
        foreach (string key in keys)
            using (RegistryKey k = Registry.CurrentUser.OpenSubKey(key))
            {
                if (k == null) continue;
                string dir = (k.GetValue("InstallLocation") as string ?? "").TrimEnd('\\');
                string v = dir.Length > 0 ? VersionIn(dir) : null;
                if (v != null) { Installed i = new Installed(); i.Dir = dir; i.Version = v; i.BySetup = true; return i; }
            }
        return null;
    }

    // Is a program running out of this folder's environment? Asked of Windows; nothing is stopped.
    static bool Running(string dir)
    {
        if (!Directory.Exists(Path.Combine(dir, ".venv"))) return false;
        string prefix = Path.Combine(dir, ".venv") + "\\";
        try
        {
            using (ManagementObjectSearcher s = new ManagementObjectSearcher("SELECT ExecutablePath FROM Win32_Process"))
                foreach (ManagementBaseObject o in s.Get())
                {
                    string p = o["ExecutablePath"] as string;
                    if (p != null && p.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) return true;
                }
        }
        catch (ManagementException) { }       // Windows would not say: the installer checks again itself
        catch (System.Runtime.InteropServices.COMException) { }
        return false;
    }

    // --- the window ---

    public void Run()
    {
        zh = Chinese();
        bool dark = Has("dark");
        if (!dark && !Has("shot"))
            try { dark = Convert.ToInt32(Registry.GetValue("HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize", "AppsUseLightTheme", 1)) == 0; }
            catch (Exception) { dark = false; }
        tok = Tokens(dark);
        string xaml;
        using (StreamReader r = new StreamReader(Assembly.GetExecutingAssembly().GetManifestResourceStream("Window.xaml"))) xaml = r.ReadToEnd();
        foreach (KeyValuePair<string, string> t in tok) xaml = xaml.Replace("{{" + t.Key + "}}", t.Value);
        win = (Window)XamlReader.Parse(xaml);
        foreach (Match m in Regex.Matches(xaml, "x:Name=\"(\\w+)\"")) ui[m.Groups[1].Value] = win.FindName(m.Groups[1].Value);
        using (Stream s = Assembly.GetExecutingAssembly().GetManifestResourceStream("logo.png"))
        {
            BitmapImage bmp = new BitmapImage();
            bmp.BeginInit(); bmp.CacheOption = BitmapCacheOption.OnLoad; bmp.StreamSource = s; bmp.EndInit();
            ((Image)ui["Logo"]).Source = bmp;
            win.Icon = bmp;
        }

        uninstallOnly = Has("uninstall") || !Engine.Present();
        inst = FindInstalled();
        if (Has("dir")) target = Arg("dir");
        else if (uninstallOnly && !Has("shot")) target = inst != null ? inst.Dir : Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        else target = inst != null ? inst.Dir : DefaultDir();
        if (Has("dir") && inst == null && VersionIn(target) != null) { inst = new Installed(); inst.Dir = target; inst.Version = VersionIn(target); }
        if (inst != null && !string.Equals(inst.Dir, target, StringComparison.OrdinalIgnoreCase))
        {
            string v = VersionIn(target);            // told where to work: what is registered elsewhere is not what is there
            if (v == null) inst = null; else { inst = new Installed(); inst.Dir = target; inst.Version = v; }
        }
        removing = uninstallOnly;
        Text("Ver").Text = removing && inst != null ? inst.Version : Build.Version;
        win.Title = T("安装 AutoApply", "AutoApply Setup");

        if (uninstallOnly && !Has("shot"))
        {
            if (VersionIn(target) == null) { MessageBox.Show(T("没有找到已安装的 AutoApply。", "No installed AutoApply was found."), Build.AppName); return; }
            // this program sits in the folder it is about to remove: go on from a copy outside it
            string me = Assembly.GetExecutingAssembly().Location;
            if (me.StartsWith(target + "\\", StringComparison.OrdinalIgnoreCase) && !Has("moved"))
            {
                string copy = Path.Combine(Path.GetTempPath(), "AutoApplySetup-" + Guid.NewGuid().ToString("N") + ".exe");
                File.Copy(me, copy, true);
                List<string> a = new List<string>();
                a.Add("/uninstall"); a.Add("/moved"); a.Add("/dir=\"" + target + "\"");
                foreach (string k in new string[] { "auto", "deletedata", "dark" }) if (Has(k)) a.Add("/" + k);
                foreach (string k in new string[] { "lang", "result" }) if (Has(k)) a.Add("/" + k + "=\"" + Arg(k) + "\"");
                Process.Start(copy, string.Join(" ", a.ToArray()));
                return;
            }
        }

        El("Header").MouseLeftButtonDown += delegate { try { win.DragMove(); } catch (InvalidOperationException) { } };
        El("LangZh").MouseLeftButtonDown += delegate(object s, MouseButtonEventArgs e) { e.Handled = true; SetLang(true); };
        El("LangEn").MouseLeftButtonDown += delegate(object s, MouseButtonEventArgs e) { e.Handled = true; SetLang(false); };
        Btn("CloseBtn").Click += delegate { win.Close(); };
        Btn("BrowseBtn").Click += delegate { Browse(); };
        Btn("SecondBtn").Click += delegate { Second(); };
        Btn("LeftBtn").Click += delegate { Left(); };
        Btn("MainBtn").Click += delegate { Main(); };
        win.Closing += delegate(object s, System.ComponentModel.CancelEventArgs e) { if (state == "work") e.Cancel = true; };
        timer.Interval = TimeSpan.FromMilliseconds(200);
        timer.Tick += delegate { Tick(); };

        SetLangUi();
        if (removing) EnterRemove(); else EnterChoose();

        if (Has("shot")) { Shot(); return; }
        if (Has("auto")) Auto();
        win.ShowDialog();
        if (engine != null) { Engine.Clean(engine); engine = null; }       // kept for "Try again" while the window was open
        if (Has("moved"))       // the copy this ran from: gone a moment after it ends
            try { Engine.Start(Environment.GetEnvironmentVariable("ComSpec"), "/d /c ping -n 3 127.0.0.1 >nul & del \"" + Assembly.GetExecutingAssembly().Location + "\""); }
            catch (System.ComponentModel.Win32Exception) { }
    }

    // the tokens of frontend/src/style.css
    static Dictionary<string, string> Tokens(bool dark)
    {
        string[] names = { "surface", "surface2", "bg", "border", "borderStrong", "text", "text2", "text3", "primary", "primaryHover", "primarySoft", "onPrimary",
                           "ok", "okSoft", "warn", "warnSoft", "bad", "badSoft", "neutralSoft", "logoTile" };
        string[] light = { "#ffffff", "#f0f3f7", "#f5f7fa", "#e1e6ee", "#c9d1dd", "#14233b", "#5a6b82", "#8b98ab", "#1f4fd8", "#1a43ba", "#e8eeff", "#ffffff",
                           "#17794a", "#e2f4ea", "#9a5b00", "#fff1d6", "#b3261e", "#fde8e6", "#edf0f5", "Transparent" };
        string[] night = { "#151d29", "#1c2634", "#0d131c", "#273244", "#3a475c", "#e7ecf3", "#a3b0c2", "#75839a", "#6f9bff", "#8aadff", "#1b2a4d", "#0b1424",
                           "#6fd3a0", "#14301f", "#f0c36a", "#3a2e12", "#f29b94", "#3d1d1b", "#222c3b", "#ffffff" };
        Dictionary<string, string> t = new Dictionary<string, string>();
        for (int i = 0; i < names.Length; i++) t[names[i]] = dark ? night[i] : light[i];
        return t;
    }

    string[] InstallSteps()
    {
        return new string[] { T("复制程序文件", "Copy the program files"), T("准备 Python", "Get Python"), T("安装依赖", "Install the dependencies"), T("准备程序用的浏览器", "Get the browser the program uses") };
    }

    string[] RemoveSteps()
    {
        return new string[] { T("删除快捷方式、开机启动项和“应用”里的登记", "Remove shortcuts, the sign-in entry and the entry under Apps"), T("删除程序文件", "Delete the program files") };
    }

    void SetLangUi()
    {
        // the segmented switch: the chosen language on the surface colour, the other one muted
        ((Border)ui["LangZh"]).Background = zh ? B("surface") : Brushes.Transparent;
        ((Border)ui["LangEn"]).Background = zh ? Brushes.Transparent : B("surface");
        Text("LangZhT").Foreground = B(zh ? "text" : "text2");
        Text("LangEnT").Foreground = B(zh ? "text2" : "text");
    }

    void SetLang(bool chinese)
    {
        if (zh == chinese) return;
        zh = chinese;
        SetLangUi();
        win.Title = T("安装 AutoApply", "AutoApply Setup");
        // redraw the page that is showing, in the new language; what the person has entered stays
        if (state == "choose") { string keep = ((TextBox)ui["PathText"]).Text; bool note = El("Notice").Visibility == Visibility.Visible; EnterChoose(); if (inst == null) ((TextBox)ui["PathText"]).Text = keep; if (note) SayRunning(); }
        else if (state == "remove") { bool all = Tog("RmAll").IsChecked == true; bool note = El("Notice").Visibility == Visibility.Visible; EnterRemove(); Tog("RmAll").IsChecked = all; Tog("RmKeep").IsChecked = !all; if (note) SayRunning(); }
        else if (state == "work") { int keep = step; EnterWork(); SetSteps(removing ? RemoveSteps() : InstallSteps(), keep, false); }
        else if (state == "done") EnterDone("");
        else if (state == "failed") EnterDone(lastError);
    }

    void ShowPage(string name)
    {
        foreach (string p in new string[] { "PgChoose", "PgRemove", "PgWork", "PgDone" }) El(p).Visibility = Vis(p == name);
        El("Notice").Visibility = Visibility.Collapsed;
        El("NetNote").Visibility = Visibility.Visible;
    }

    void SetSteps(string[] labels, int current, bool failed)
    {
        StackPanel steps = (StackPanel)ui["Steps"];
        steps.Children.Clear();
        for (int i = 0; i < labels.Length; i++)
        {
            StackPanel row = new StackPanel(); row.Orientation = Orientation.Horizontal; row.Margin = new Thickness(0, 0, 0, 9);
            Border dot = new Border(); dot.Width = 20; dot.Height = 20; dot.CornerRadius = new CornerRadius(10); dot.VerticalAlignment = VerticalAlignment.Center;
            TextBlock g = new TextBlock(); g.FontSize = 12; g.FontWeight = FontWeights.Bold; g.HorizontalAlignment = HorizontalAlignment.Center; g.VerticalAlignment = VerticalAlignment.Center;
            TextBlock lab = new TextBlock(); lab.Text = labels[i]; lab.Margin = new Thickness(10, 0, 0, 0); lab.VerticalAlignment = VerticalAlignment.Center;
            if (i < current) { dot.Background = B("okSoft"); g.Text = "\u2713"; g.Foreground = B("ok"); lab.Foreground = B("text2"); }
            else if (i == current && failed) { dot.Background = B("badSoft"); g.Text = "\u2715"; g.Foreground = B("bad"); lab.FontWeight = FontWeights.SemiBold; }
            else if (i == current) { dot.Background = B("primary"); g.Text = (i + 1).ToString(); g.Foreground = B("onPrimary"); lab.FontWeight = FontWeights.SemiBold; }
            else { dot.Background = B("neutralSoft"); g.Text = (i + 1).ToString(); g.Foreground = B("text3"); lab.Foreground = B("text3"); }
            dot.Child = g; row.Children.Add(dot); row.Children.Add(lab); steps.Children.Add(row);
        }
    }

    // The bar: how many steps are behind, plus how far the current one says it is. A step that reports nothing
    // pulses instead - it says "working", not "how far".
    void SetBar(int count, int current, int percent)
    {
        Border bar = (Border)ui["Bar"];
        double part = percent >= 0 ? percent / 100.0 : 0.12;
        bar.Width = Math.Max(0.0, Math.Min(1.0, (current + part) / count)) * 584.0;
        if (percent < 0 && state == "work")
        {
            if (!bar.HasAnimatedProperties)
            {
                DoubleAnimation a = new DoubleAnimation(1.0, 0.35, new Duration(TimeSpan.FromMilliseconds(800)));
                a.AutoReverse = true; a.RepeatBehavior = RepeatBehavior.Forever;
                bar.BeginAnimation(UIElement.OpacityProperty, a);
            }
        }
        else bar.BeginAnimation(UIElement.OpacityProperty, null);
    }

    // --- the pages ---

    void EnterChoose()
    {
        state = "choose"; ShowPage("PgChoose");
        Btn("LeftBtn").Visibility = Visibility.Collapsed; Btn("SecondBtn").Visibility = Visibility.Collapsed; Btn("MainBtn").IsEnabled = true; Btn("CloseBtn").Visibility = Visibility.Visible;
        Tog("OptDesktop").Content = T("添加桌面快捷方式", "Add a desktop shortcut"); Tog("OptStart").Content = T("添加到开始菜单", "Add to the Start menu"); Tog("OptAuto").Content = T("开机时自动启动", "Start when I sign in");
        Text("NetNote").Text = T("安装过程会联网下载 Python 和依赖（来自 GitHub 和 pypi.org），以及程序自己用的浏览器（Chromium）。第一次约 600 MB，需要几分钟。只装在你的用户目录里，不需要管理员权限。",
                                 "Setup downloads Python and the dependencies (from GitHub and pypi.org) and the browser the program uses (Chromium): about 600 MB and a few minutes the first time. Everything goes into your user folder; no administrator rights are needed.");
        if (inst != null)
        {
            bool same = inst.Version == Build.Version;
            Text("ChTitle").Text = same ? T("已经安装了 AutoApply", "AutoApply is already installed") : T("升级 AutoApply", "Upgrade AutoApply");
            Text("ChSub").Text = same ? T("这台电脑上已经有同一个版本。可以修复它（重新复制程序文件、补齐环境），或者卸载。", "The same version is already on this computer. You can repair it (copy the program files again, complete the environment) or remove it.")
                                      : T("会用这个版本替换程序文件。你的数据原样保留；新版本没能准备好时，会恢复成现在的版本。", "The program files are replaced with this version. Your data stays as it is, and if the new version cannot be made ready, the one you have now is put back.");
            El("ExistBox").Visibility = Visibility.Visible;
            Text("ExistHead").Text = T("已安装的版本：", "Installed version: ") + inst.Version + T("　　这个安装包：", "      This package: ") + Build.Version;
            Text("ExistPath").Text = T("位置：", "Location: ") + inst.Dir;
            Text("ExistNote").Text = T("岗位、草案、个人资料、上传的文件（data 和 knowledge 文件夹）不会被改动。", "Jobs, drafts, your profile and uploaded files (the data and knowledge folders) are not touched.");
            El("PathBox").Visibility = Visibility.Collapsed; El("OptBox").Visibility = Visibility.Visible;
            if (!optsSeen)
            {
                // A copy that setup installed before: the boxes show what is there now, so an upgrade keeps the earlier choice.
                // A copy that was unzipped and started by hand has made no such choice: both shortcuts are offered, ticked.
                optsSeen = true;
                string lnk = Build.AppName + ".lnk";
                Tog("OptDesktop").IsChecked = !inst.BySetup || File.Exists(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), lnk));
                Tog("OptStart").IsChecked = !inst.BySetup || File.Exists(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), lnk));
                using (RegistryKey k = Registry.CurrentUser.OpenSubKey(RunKey)) Tog("OptAuto").IsChecked = k != null && k.GetValue(Build.AppName) != null;
            }
            Btn("MainBtn").Content = same ? T("修复", "Repair") : T("升级到 ", "Upgrade to ") + Build.Version;
            Btn("SecondBtn").Visibility = Visibility.Visible; Btn("SecondBtn").Style = (Style)win.FindResource("Danger"); Btn("SecondBtn").Content = T("卸载…", "Uninstall...");
        }
        else
        {
            Text("ChTitle").Text = T("安装 AutoApply", "Install AutoApply");
            Text("ChSub").Text = T("在你自己电脑上运行的求职助手：找岗位、按你的规则评分、准备申请草案，你批准后替你填表。", "A job-search assistant that runs on your own computer: it finds postings, scores them by your rules, prepares each application as a draft and fills in the form after you approve it.");
            El("ExistBox").Visibility = Visibility.Collapsed; El("PathBox").Visibility = Visibility.Visible; El("OptBox").Visibility = Visibility.Visible;
            Text("PathLabel").Text = T("安装位置", "Install location"); Btn("BrowseBtn").Content = T("浏览…", "Browse..."); ((TextBox)ui["PathText"]).Text = target;
            Text("PathHint").Text = T("程序和你的数据都放在这个文件夹里（数据在其中的 data 和 knowledge）。需要约 1.5 GB 空间。", "The program and your data both live in this folder (data in its data and knowledge subfolders). About 1.5 GB is needed.");
            Text("PathHint").Foreground = B("text3");
            Btn("MainBtn").Content = T("安装", "Install");
        }
    }

    void EnterRemove()
    {
        state = "remove"; removing = true; ShowPage("PgRemove");
        Text("RmTitle").Text = T("卸载 AutoApply", "Uninstall AutoApply");
        Text("RmSub").Text = T("位置：", "Location: ") + target;
        Text("RmKeepT").Text = T("保留我的数据", "Keep my data");
        Text("RmKeepD").Text = T("只删除程序。岗位、草案、个人资料和上传的文件留在原文件夹里，以后重新安装可以接着用。", "Only the program is removed. Jobs, drafts, your profile and uploaded files stay in the folder, and a later install picks them up again.");
        Text("RmAllT").Text = T("连数据一起删除", "Delete my data too");
        Text("RmAllD").Text = T("整个文件夹都会删除，无法恢复。想留一份的话，先在程序的“设置 → 高级”里导出。", "The whole folder is deleted and cannot be brought back. To keep a copy, export it first under Settings > Advanced in the program.");
        Text("RmNote").Text = T("程序保存的密码和 API key 在 Windows 的“凭据管理器”里（名称含 autoapply），卸载不会动它们，需要的话请在那里删除。", "Passwords and API keys the program stored are in the Windows Credential Manager (names containing autoapply). Uninstalling leaves them; remove them there if you wish.");
        Btn("MainBtn").Content = T("卸载", "Uninstall"); Btn("MainBtn").IsEnabled = true; Btn("CloseBtn").Visibility = Visibility.Visible;
        Btn("SecondBtn").Visibility = Visibility.Collapsed;
        Btn("LeftBtn").Visibility = Vis(!uninstallOnly); Btn("LeftBtn").Content = T("← 返回", "← Back");
    }

    void SayRunning()
    {
        Text("NoticeT").Text = T("这个文件夹里的 AutoApply 正在运行。请先退出它：右键点托盘里的图标，选“退出”；如果正在填写某份申请，等它填完。然后再点一次。",
                                 "AutoApply is running from this folder. Quit it first: right-click its icon in the tray and choose Quit; if an application is being filled in, let it finish. Then press the button again.");
        El("Notice").Visibility = Visibility.Visible;
        El("NetNote").Visibility = Visibility.Collapsed;        // the notice takes its place
    }

    void EnterWork()
    {
        state = "work"; ShowPage("PgWork");
        Text("WkTitle").Text = removing ? T("正在卸载…", "Uninstalling...") : inst != null ? T("正在更新…", "Updating...") : T("正在安装…", "Installing...");
        Text("WkSub").Text = removing ? target : T("第一次需要几分钟，主要是下载。这个窗口可以放在一边。", "A few minutes the first time, mostly downloading. You can leave this window alone.");
        SetSteps(removing ? RemoveSteps() : InstallSteps(), step, false); Text("WkLine").Text = "";
        Btn("MainBtn").IsEnabled = false; Btn("MainBtn").Content = T("请稍候", "Please wait"); Btn("LeftBtn").Visibility = Visibility.Collapsed; Btn("CloseBtn").Visibility = Visibility.Hidden;
        Btn("SecondBtn").Visibility = Vis(!removing); Btn("SecondBtn").Style = (Style)win.FindResource("Btn"); Btn("SecondBtn").IsEnabled = !cancelSent;
        Btn("SecondBtn").Content = cancelSent ? T("正在停止…", "Stopping...") : T("取消", "Cancel");
    }

    void EnterDone(string err)
    {
        ShowPage("PgDone"); Btn("CloseBtn").Visibility = Visibility.Visible; Btn("MainBtn").IsEnabled = true; Btn("SecondBtn").Visibility = Visibility.Collapsed; Btn("LeftBtn").Visibility = Visibility.Collapsed;
        ((Border)ui["Bar"]).BeginAnimation(UIElement.OpacityProperty, null);
        lastError = err;
        Border icon = (Border)ui["DoneIcon"]; System.Windows.Shapes.Path glyph = (System.Windows.Shapes.Path)ui["DoneGlyph"];
        if (err.Length > 0)
        {
            state = "failed";
            icon.Background = B("badSoft"); glyph.Stroke = B("bad"); glyph.Data = Geometry.Parse("M2,2 L18,18 M18,2 L2,18");
            Text("DnTitle").Text = removing ? T("没有卸载完", "The uninstall did not finish") : T("没有装完", "Setup did not finish");
            Text("DnSub").Text = Message(err);
            Tog("DnLaunch").Visibility = Visibility.Collapsed;
            Btn("MainBtn").Content = T("再试一次", "Try again");
            Btn("LeftBtn").Visibility = Visibility.Visible; Btn("LeftBtn").Content = T("查看日志", "Show the log");
        }
        else
        {
            state = "done";
            icon.Background = B("okSoft"); glyph.Stroke = B("ok"); glyph.Data = Geometry.Parse("M2,11 L8.5,17.5 L21,4");
            if (removing)
            {
                Text("DnTitle").Text = T("已卸载", "Uninstalled");
                Text("DnSub").Text = Tog("RmAll").IsChecked == true ? T("程序和数据都已删除。", "The program and its data were deleted.") : T("程序已删除。你的数据还在：", "The program was removed. Your data is still in: ") + target;
                Tog("DnLaunch").Visibility = Visibility.Collapsed;
            }
            else
            {
                Text("DnTitle").Text = inst != null ? T("更新完成", "Updated") : T("安装完成", "Installed");
                Text("DnSub").Text = T("以后从桌面或开始菜单里的 AutoApply 启动。启动后屏幕右下角的托盘里会有它的图标，网页会自动打开。", "Start it with the AutoApply shortcut on the desktop or in the Start menu. Its icon then sits in the tray and the page opens by itself.");
                Tog("DnLaunch").Visibility = Visibility.Visible; Tog("DnLaunch").Content = T("现在启动 AutoApply", "Start AutoApply now");
            }
            Btn("MainBtn").Content = T("完成", "Done");
        }
    }

    // What went wrong, in words. The codes are the ones scripts/prepare.py ends with, plus this program's own.
    string Message(string code)
    {
        switch (code)
        {
            case "cancelled": return T("你停止了安装。如果之前装有旧版本，它已经恢复原样。再试一次会接着来，已经下载的内容不会重新下载。", "You stopped the installation. If a version was installed before, it is back in place. Trying again continues; what was already downloaded is kept.");
            case "bootstrap": return T("Python 下载失败（多数是网络问题）。之前安装的内容没有被改动。", "Python could not be downloaded (usually the network). Nothing that was installed before was changed.");
            case "files": return T("新版本的文件放置失败（可能有文件被别的程序占用）。之前的版本没有被改动。", "The new files could not be put in place (a file may be open in another program). The previous version is untouched.");
            case "deps": return T("依赖安装失败（多数是网络问题）。再试一次会接着来，已经下载的内容不会重新下载。", "The dependencies could not be installed (usually the network). Trying again continues; what was already downloaded is kept.");
            case "deps_restored": return T("新版本的依赖安装失败（多数是网络问题）。之前的版本已经恢复，可以照常使用。", "The dependencies of the new version could not be installed (usually the network). The previous version was put back and works.");
            case "deps_broken": return T("依赖安装失败，旧版本的依赖也没能恢复。你的数据没有被改动。请在网络正常时再试一次。", "The dependencies could not be installed, and the previous version's could not be restored. Your data is untouched. Try again when the network works.");
            case "browser": return T("程序用的浏览器下载失败（多数是网络问题）。其余部分已经装好，再试一次即可完成。", "The browser the program uses could not be downloaded (usually the network). Everything else is installed; trying again finishes it.");
            case "running": return T("AutoApply 还在运行，所以什么都没有改动。请先从托盘图标退出它。", "AutoApply is still running, so nothing was changed. Quit it from its tray icon first.");
            case "remove": return T("有些程序文件没能删除（可能还有程序开着它们）。你的数据没有被改动。", "Some program files could not be deleted (a program may still have them open). Your data is untouched.");
            case "engine": return T("安装程序本身不完整，请重新下载。", "This setup program is incomplete. Download it again.");
            default: return T("安装没有完成（", "Setup did not finish (") + code + T("）。详细情况在日志里。", "). The log has the details.");
        }
    }

    // --- the buttons ---

    void Browse()
    {
        using (System.Windows.Forms.FolderBrowserDialog dlg = new System.Windows.Forms.FolderBrowserDialog())
        {
            dlg.Description = T("选一个文件夹，AutoApply 会装到它里面的 AutoApply 子文件夹", "Choose a folder; AutoApply goes into an AutoApply subfolder of it");
            if (dlg.ShowDialog() != System.Windows.Forms.DialogResult.OK) return;
            string p = dlg.SelectedPath;
            if (!string.Equals(Path.GetFileName(p), Build.AppName, StringComparison.OrdinalIgnoreCase)) p = Path.Combine(p, Build.AppName);
            ((TextBox)ui["PathText"]).Text = p;
        }
    }

    void Second()
    {
        if (state == "choose") { EnterRemove(); return; }
        if (state != "work" || removing || cancelSent) return;
        // Cancel, pressed twice: the first press asks, so that a slip does not throw away minutes of downloading
        if (!cancelAsked || (DateTime.Now - cancelAskedAt).TotalSeconds > 6)
        {
            cancelAsked = true; cancelAskedAt = DateTime.Now;
            Btn("SecondBtn").Content = T("再点一次确认停止", "Press again to stop"); Btn("SecondBtn").Style = (Style)win.FindResource("Danger");
            return;
        }
        cancelSent = true;
        File.WriteAllText(Path.Combine(statusDir, "prepare.cancel"), "x");
        Btn("SecondBtn").IsEnabled = false; Btn("SecondBtn").Style = (Style)win.FindResource("Btn"); Btn("SecondBtn").Content = T("正在停止…", "Stopping...");
    }

    void Left()
    {
        if (state == "remove") { removing = false; EnterChoose(); return; }
        if (state != "failed") return;
        string log = null;
        try
        {
            DirectoryInfo d = new DirectoryInfo(Path.Combine(target, "data", "logs"));
            if (d.Exists) foreach (FileInfo f in d.GetFiles("setup-*.log")) if (log == null || f.LastWriteTime > File.GetLastWriteTime(log)) log = f.FullName;
        }
        catch (IOException) { }
        if (log != null) Process.Start("notepad.exe", "\"" + log + "\"");
        else MessageBox.Show(T("这次没有留下日志（还没进行到写日志的那一步）。", "There is no log for this attempt (it did not get as far as writing one)."), Build.AppName);
    }

    void Main()
    {
        if (state == "choose")
        {
            if (inst == null)
            {
                string p = ((TextBox)ui["PathText"]).Text.Trim().Trim('"');
                string bad = null;
                if (p.Length == 0 || !Path.IsPathRooted(p) || p.IndexOfAny(Path.GetInvalidPathChars()) >= 0) bad = T("请填写完整的文件夹路径，例如 D:\\Apps\\AutoApply。", "Give a full folder path, for example D:\\Apps\\AutoApply.");
                else if (Directory.Exists(p) && VersionIn(p) == null && Directory.GetFileSystemEntries(p).Length > 0 && !OnlyData(p)) bad = T("这个文件夹里已经有别的东西了。请选一个空文件夹，或让程序新建一个。", "That folder already has other things in it. Choose an empty folder, or let setup create a new one.");
                else
                    try { Directory.CreateDirectory(p); }
                    catch (Exception e) { bad = T("不能在这里创建文件夹：", "A folder cannot be created there: ") + e.Message; }
                if (bad != null) { Text("PathHint").Text = bad; Text("PathHint").Foreground = B("bad"); return; }
                target = p;
            }
            removing = false;
            Begin();
        }
        else if (state == "remove" || state == "failed") Begin();
        else if (state == "done")
        {
            if (!removing && Tog("DnLaunch").IsChecked == true)
            {
                string pyw = Path.Combine(target, ".venv", "Scripts", "pythonw.exe");
                if (File.Exists(pyw)) { ProcessStartInfo i = new ProcessStartInfo(pyw, "-m autoapply.launcher"); i.WorkingDirectory = target; i.UseShellExecute = false; Process.Start(i); }
            }
            win.Close();
        }
    }

    // what an uninstall that kept the data leaves behind: installing there again picks it up
    static bool OnlyData(string dir)
    {
        foreach (string e in Directory.GetFileSystemEntries(dir))
        {
            string n = Path.GetFileName(e).ToLowerInvariant();
            if (n != "data" && n != "knowledge") return false;
        }
        return true;
    }

    // --- the work: started here, done by the installer ---

    void Begin()
    {
        if (Running(target))
        {
            if (state == "failed") { if (removing) EnterRemove(); else EnterChoose(); }
            SayRunning();
            if (Has("auto")) Finish("running");
            return;
        }
        step = 0; cancelAsked = false; cancelSent = false; began = DateTime.Now;
        string arguments;
        string exe;
        if (removing)
        {
            exe = Path.Combine(target, "unins000.exe");
            arguments = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART" + (Tog("RmAll").IsChecked == true || Has("deletedata") ? " /DELETEDATA" : "");
            if (Has("deletedata")) Tog("RmAll").IsChecked = true;
            if (!File.Exists(exe)) { Legacy(); return; }
        }
        else
        {
            if (engine == null) engine = Engine.Extract();
            if (engine == null) { EnterWork(); Finish("engine"); return; }
            exe = engine;
            statusDir = Path.Combine(Path.GetDirectoryName(engine), "status-" + DateTime.Now.Ticks);
            Directory.CreateDirectory(statusDir);
            List<string> tasks = new List<string>();
            if (!Has("notasks"))
            {
                if (Tog("OptDesktop").IsChecked == true) tasks.Add("desktopicon");
                if (Tog("OptStart").IsChecked == true) tasks.Add("startmenuicon");
                if (Tog("OptAuto").IsChecked == true) tasks.Add("autostart");
            }
            arguments = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=\"" + target + "\" /LANG=" + (zh ? "zh" : "en") + " /TASKS=\"" + string.Join(",", tasks.ToArray()) + "\" /STATUSDIR=\"" + statusDir + "\"";
        }
        EnterWork();
        try { proc = Engine.Start(exe, arguments); }
        catch (System.ComponentModel.Win32Exception) { Finish("engine"); return; }
        removeUntil = DateTime.MinValue;
        timer.Start();
    }

    // A copy installed by versions up to 1.0.3 has no Inno Setup uninstaller: there is nothing registered to undo
    // beyond what is done here.
    void Legacy()
    {
        EnterWork();
        try
        {
            foreach (Environment.SpecialFolder f in new Environment.SpecialFolder[] { Environment.SpecialFolder.DesktopDirectory, Environment.SpecialFolder.Programs })
                File.Delete(Path.Combine(Environment.GetFolderPath(f), "AutoApply.lnk"));
            using (RegistryKey k = Registry.CurrentUser.OpenSubKey(RunKey, true)) if (k != null) k.DeleteValue("AutoApply", false);
            Registry.CurrentUser.DeleteSubKeyTree(Uninstall + "AutoApply", false);
            bool all = Tog("RmAll").IsChecked == true;
            foreach (string e in Directory.GetFileSystemEntries(target))
            {
                string n = Path.GetFileName(e).ToLowerInvariant();
                if (!all && (n == "data" || n == "knowledge")) continue;
                if (Directory.Exists(e)) Directory.Delete(e, true); else File.Delete(e);
            }
            if (all) Directory.Delete(target, true);
            Finish("");
        }
        catch (IOException) { Finish("remove"); }
        catch (UnauthorizedAccessException) { Finish("remove"); }
    }

    void Tick()
    {
        if (removing) { TickRemove(); return; }
        int percent = -1, part = 0;
        try
        {
            string f = Path.Combine(statusDir, "prepare.status");
            if (File.Exists(f))
            {
                string[] v = File.ReadAllText(f).Trim().Split(' ');
                if (v.Length >= 2)
                {
                    int s = int.Parse(v[0]);
                    step = s <= 1 ? 1 : s;                      // 0 Python and 1 placing the files show as one step
                    percent = int.Parse(v[1]);
                    if (v.Length >= 3) part = int.Parse(v[2]);
                }
            }
        }
        catch (IOException) { }                 // being rewritten this instant: the next tick reads it
        catch (FormatException) { }
        string[] labels = InstallSteps();
        if (step >= labels.Length) step = labels.Length - 1;
        SetSteps(labels, step, false);
        SetBar(labels.Length, step, percent);
        TimeSpan t = DateTime.Now - began;
        string clock = string.Format("{0}:{1:00}", (int)t.TotalMinutes, t.Seconds);
        if (cancelSent) Text("WkLine").Text = T("正在停止，并恢复原样…", "Stopping, and putting things back...");
        else if (percent >= 0) Text("WkLine").Text = (part > 1 ? T("第 " + part + " 个下载：", "Download " + part + ": ") : T("已下载 ", "Downloaded ")) + percent + "%" + T("　·　已用时 ", "  ·  ") + clock;
        else Text("WkLine").Text = T("已用时 ", "Elapsed ") + clock;
        if (cancelAsked && !cancelSent && (DateTime.Now - cancelAskedAt).TotalSeconds > 6)
        {
            cancelAsked = false; Btn("SecondBtn").Content = T("取消", "Cancel"); Btn("SecondBtn").Style = (Style)win.FindResource("Btn");
        }
        if (!proc.HasExited) return;
        timer.Stop();
        int code = proc.ExitCode; proc.Dispose(); proc = null;
        string result = "";
        try { string d = Path.Combine(statusDir, "prepare.done"); if (File.Exists(d)) result = File.ReadAllText(d).Trim(); }
        catch (IOException) { }
        if (result == "ok" && code == 0) Finish("");
        else if (result.StartsWith("error ")) Finish(result.Substring(6));
        else if (result == "cancelled") Finish("cancelled");
        else if (Running(target)) Finish("running");
        else Finish("exit " + code);
    }

    // The uninstaller hands over to a copy of itself and returns at once: what counts is that the files are gone.
    void TickRemove()
    {
        string[] labels = RemoveSteps();
        bool gone = !File.Exists(Path.Combine(target, "unins000.exe")) && !Directory.Exists(Path.Combine(target, "backend")) && !Directory.Exists(Path.Combine(target, ".venv"));
        if (proc != null && proc.HasExited) { proc.Dispose(); proc = null; removeUntil = DateTime.Now.AddMinutes(3); }
        step = proc == null ? 1 : 0;
        SetSteps(labels, step, false); SetBar(labels.Length, step, -1);
        if (proc != null) return;
        if (gone) { timer.Stop(); Finish(""); }
        else if (DateTime.Now > removeUntil) { timer.Stop(); Finish("remove"); }
    }

    void Finish(string error)
    {
        if (error.Length > 0) SetSteps(removing ? RemoveSteps() : InstallSteps(), step, true);
        if (error.Length == 0 && !removing && engine != null) { Engine.Clean(engine); engine = null; }
        EnterDone(error);
        if (!Has("auto")) return;
        Program.ExitCode = error.Length == 0 ? 0 : 1;
        if (Has("result")) File.WriteAllText(Arg("result"), state + "|" + Text("DnTitle").Text + "|" + Text("DnSub").Text + "|lang: " + langCheck + (error.Length > 0 ? "|" + error : ""));
        Tog("DnLaunch").IsChecked = false;
        state = "closed";
        win.Dispatcher.BeginInvoke(new Action(delegate { win.Close(); }));
    }

    // --- checking without clicking ---

    // the real window, driven the way a person would: switch the language and back, press the main button, wait
    void Auto()
    {
        DispatcherTimer driver = new DispatcherTimer();
        driver.Interval = TimeSpan.FromMilliseconds(500);
        driver.Tick += delegate
        {
            if (pressed || (state != "choose" && state != "remove")) return;
            pressed = true; driver.Stop();
            string before = state == "choose" ? Text("ChTitle").Text : Text("RmTitle").Text;
            SetLang(!zh);
            string other = state == "choose" ? Text("ChTitle").Text : Text("RmTitle").Text;
            SetLang(!zh);
            langCheck = before + " -> " + other;
            Btn("MainBtn").RaiseEvent(new RoutedEventArgs(ButtonBase.ClickEvent));
        };
        driver.Start();
    }

    // draw one page to a file, for review; nothing is installed
    void Shot()
    {
        string page = Arg("page");
        Installed fake = new Installed(); fake.Dir = target; fake.BySetup = true;
        if (page == "existing") { fake.Version = "0.9.0"; inst = fake; optsSeen = true; EnterChoose(); }
        else if (page == "same") { fake.Version = Build.Version; inst = fake; optsSeen = true; EnterChoose(); }
        else if (page == "running") { inst = null; EnterChoose(); SayRunning(); }
        else if (page == "progress") { inst = null; removing = false; step = 3; EnterWork(); SetBar(4, 3, 40); Text("WkLine").Text = T("已下载 40%　·　已用时 2:14", "Downloaded 40%  ·  2:14"); }
        else if (page == "done") { inst = null; removing = false; EnterDone(""); }
        else if (page == "failed") { inst = null; removing = false; step = 2; EnterWork(); SetSteps(InstallSteps(), 2, true); EnterDone("deps_restored"); }
        else if (page == "uninstall") { removing = true; EnterRemove(); }
        else { inst = null; removing = false; EnterChoose(); }
        win.ShowInTaskbar = false; win.WindowStartupLocation = WindowStartupLocation.Manual; win.Left = -3000; win.Top = -3000;
        win.Show(); win.UpdateLayout();
        win.Dispatcher.Invoke(new Action(delegate { }), DispatcherPriority.Render);
        double scale = 2.0;
        RenderTargetBitmap rtb = new RenderTargetBitmap((int)(win.ActualWidth * scale), (int)(win.ActualHeight * scale), 96 * scale, 96 * scale, PixelFormats.Pbgra32);
        rtb.Render((Visual)win.Content);
        PngBitmapEncoder enc = new PngBitmapEncoder();
        enc.Frames.Add(BitmapFrame.Create(rtb));
        using (FileStream fs = File.Create(Arg("shot"))) enc.Save(fs);
        win.Close();
    }
}
