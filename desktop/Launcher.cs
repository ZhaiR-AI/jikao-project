using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

static class Program
{
    [STAThread]
    static int Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        string root = AppDomain.CurrentDomain.BaseDirectory;
        using (var service = new LocalService(root))
        {
            if (args.Length > 0 && args[0] == "--smoke-test")
            {
                try
                {
                    service.Start();
                    foreach (string path in new[] { "/exam", "/study", "/wrong-book", "/api/paper/-/collections" })
                        service.Request(path, "GET");
                    service.Stop();
                    File.WriteAllText(Path.Combine(root, "smoke-result.txt"), "PASS: embedded runtime, pages, empty data, graceful shutdown", Encoding.UTF8);
                    return 0;
                }
                catch (Exception ex)
                {
                    File.WriteAllText(Path.Combine(root, "smoke-result.txt"), "FAIL: " + ex.Message, Encoding.UTF8);
                    return 1;
                }
            }
            // A file lock prevents two launchers from using the same data directory.
            try
            {
                using (var instance = new FileStream(Path.Combine(root, ".launcher.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None))
                    Application.Run(new LauncherForm(root, service));
            }
            catch (IOException)
            {
                MessageBox.Show("程序已打开，或者当前目录不可写。请查看任务栏中的成考助手；若未打开，请把整个文件夹解压到桌面或文档后重试。", "无法启动");
                return 1;
            }
        }
        return 0;
    }
}

sealed class LocalService : IDisposable
{
    public readonly string AppDirectory;
    readonly string root;
    readonly object logLock = new object();
    Process process;
    string token;
    public string Url { get; private set; }
    public bool Running { get { return process != null && !process.HasExited; } }

    public LocalService(string rootDirectory)
    {
        root = rootDirectory;
        AppDirectory = Path.Combine(root, "程序文件", "app");
    }

    void Log(string text)
    {
        if (text == null) return;
        lock (logLock)
        {
            try { File.AppendAllText(Path.Combine(root, "启动日志.txt"), text + Environment.NewLine, Encoding.UTF8); }
            catch (IOException) { }
        }
    }

    public string Request(string path, string method)
    {
        var request = (HttpWebRequest)WebRequest.Create(Url + path);
        request.Proxy = null;
        request.Timeout = 1500;
        request.ReadWriteTimeout = 1500;
        request.Method = method;
        request.Headers.Add("X-Desktop-Token", token);
        if (method == "POST") request.ContentLength = 0;
        using (var response = request.GetResponse())
        using (var reader = new StreamReader(response.GetResponseStream()))
            return reader.ReadToEnd();
    }

    public void Start()
    {
        if (Running) return;
        if (process != null) { process.Dispose(); process = null; }
        string python = Path.Combine(root, "程序文件", "python", "python.exe");
        if (!File.Exists(python)) throw new Exception("找不到随软件提供的运行环境。请完整解压安装包，不要只复制 EXE。");
        var probe = new TcpListener(IPAddress.Loopback, 0);
        probe.Start();
        int port = ((IPEndPoint)probe.LocalEndpoint).Port;
        probe.Stop();
        Url = "http://127.0.0.1:" + port;
        token = Guid.NewGuid().ToString("N");
        var info = new ProcessStartInfo(python, "-B -u desktop_server.py");
        info.WorkingDirectory = AppDirectory;
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        info.RedirectStandardOutput = true;
        info.RedirectStandardError = true;
        info.StandardOutputEncoding = Encoding.UTF8;
        info.StandardErrorEncoding = Encoding.UTF8;
        info.EnvironmentVariables["PAPER_PORT"] = port.ToString();
        info.EnvironmentVariables["PAPER_DESKTOP_TOKEN"] = token;
        info.EnvironmentVariables["PAPER_DESKTOP_PARENT"] = Process.GetCurrentProcess().Id.ToString();
        info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        Log("Starting local desktop service: " + DateTime.Now.ToString("s"));
        process = new Process();
        process.StartInfo = info;
        process.OutputDataReceived += (s, e) => Log(e.Data);
        process.ErrorDataReceived += (s, e) => Log(e.Data);
        process.Start();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        for (int i = 0; i < 120; i++)
        {
            if (process.HasExited) throw new Exception("服务启动失败。请检查目录中的“启动日志.txt”；确认已完整解压，并使用 Windows 10/11 的 64 位系统。");
            try { Request("/_desktop/status", "GET"); return; }
            catch (WebException) { Thread.Sleep(250); }
        }
        Stop();
        throw new Exception("服务启动超时。请查看“启动日志.txt”，确认程序文件未被安全软件隔离后重试。");
    }

    public void Stop()
    {
        if (process == null) return;
        if (!process.HasExited)
        {
            try { Request("/_desktop/stop", "POST"); } catch (WebException) { }
            if (!process.WaitForExit(10000)) { process.Kill(); process.WaitForExit(3000); }
        }
        process.Dispose();
        process = null;
    }

    public void Dispose() { Stop(); }
}

sealed class LauncherForm : Form
{
    readonly string root;
    readonly LocalService service;
    readonly TextBox endpoint = new TextBox();
    readonly TextBox model = new TextBox();
    readonly TextBox key = new TextBox();
    readonly Label status = new Label();
    readonly Button start = new Button();
    readonly Button stop = new Button();
    bool busy;
    bool closing;

    public LauncherForm(string rootDirectory, LocalService localService)
    {
        root = rootDirectory;
        service = localService;
        Text = "成考助手 · Windows 本地版";
        ClientSize = new Size(650, 445);
        Font = new Font("Microsoft YaHei UI", 10F);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        AddLabel("第一次使用：填写模型平台提供的三项信息", 22, 20, 600, 28);
        AddLabel("无需安装 Python。模型调用使用你自己的账号和额度。", 22, 53, 605, 28);
        AddField("接口地址", endpoint, 96);
        AddField("模型名称", model, 143);
        AddField("API Key", key, 190);
        key.UseSystemPasswordChar = true;
        var show = new CheckBox { Text = "显示密钥", Left = 126, Top = 230, Width = 130 };
        show.CheckedChanged += (s, e) => { key.UseSystemPasswordChar = !show.Checked; };
        Controls.Add(show);
        var guide = new LinkLabel { Text = "不会填写？查看配置教程", Left = 380, Top = 232, Width = 240 };
        guide.LinkClicked += (s, e) => OpenPath(Path.Combine(root, "使用说明.html"));
        Controls.Add(guide);
        start.Text = "保存配置并启动"; start.SetBounds(22, 273, 185, 42);
        start.Click += async (s, e) => await StartApp(true);
        Controls.Add(start);
        var browse = new Button { Text = "打开页面", Left = 222, Top = 273, Width = 120, Height = 42 };
        browse.Click += async (s, e) => await StartApp(false);
        Controls.Add(browse);
        stop.Text = "停止服务"; stop.SetBounds(357, 273, 120, 42);
        stop.Click += async (s, e) => { if (!busy) { SetBusy(true); await Task.Run(() => service.Stop()); SetBusy(false); status.Text = "服务已停止，卷子和学习记录已保留。"; } };
        Controls.Add(stop);
        var data = new Button { Text = "数据目录", Left = 492, Top = 273, Width = 135, Height = 42 };
        data.Click += (s, e) => { string path = Path.Combine(service.AppDirectory, "data"); Directory.CreateDirectory(path); OpenPath(path); };
        Controls.Add(data);
        status.SetBounds(22, 333, 605, 55);
        status.Text = "首次使用请填写配置；也可先点“打开页面”浏览空白界面。";
        Controls.Add(status);
        AddLabel("关闭此窗口会停止服务。更新前请停止服务并备份数据目录。", 22, 399, 615, 30);
        LoadSettings();
        Shown += async (s, e) => { if (HasSettings()) await StartApp(false); };
        FormClosing += async (s, e) =>
        {
            if (closing) return;
            e.Cancel = true;
            if (busy) { status.Text = "正在处理，请稍候再关闭。"; return; }
            if (service.Running && MessageBox.Show("关闭会停止本地服务。请先保存网页作答，等待正在生成或判卷的任务完成。确定关闭？", "退出成考助手", MessageBoxButtons.OKCancel) != DialogResult.OK) return;
            SetBusy(true);
            await Task.Run(() => service.Stop());
            closing = true;
            Close();
        };
    }

    void AddLabel(string text, int x, int y, int width, int height)
    { Controls.Add(new Label { Text = text, Left = x, Top = y, Width = width, Height = height }); }

    void AddField(string text, TextBox field, int y)
    { AddLabel(text, 22, y + 4, 100, 30); field.SetBounds(126, y, 500, 32); Controls.Add(field); }

    bool HasSettings()
    { return !String.IsNullOrWhiteSpace(endpoint.Text) && !String.IsNullOrWhiteSpace(model.Text) && !String.IsNullOrWhiteSpace(key.Text); }

    void LoadSettings()
    {
        string file = Path.Combine(service.AppDirectory, "models.json");
        if (!File.Exists(file)) return;
        try
        {
            var config = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(file));
            var models = (System.Collections.ArrayList)config["models"];
            foreach (Dictionary<string, object> entry in models)
            {
                if (Convert.ToString(entry["id"]) != Convert.ToString(config["default"])) continue;
                endpoint.Text = Convert.ToString(entry["base_url"]);
                model.Text = Convert.ToString(entry["model"]);
                key.Text = Convert.ToString(entry["api_key"]);
                if (model.Text.Contains("REPLACE_WITH") || key.Text.Contains("REPLACE_WITH")) { endpoint.Clear(); model.Clear(); key.Clear(); }
                break;
            }
        }
        catch { status.Text = "已有配置无法读取。请查看教程后重新填写三项信息。"; }
    }

    void SaveSettings()
    {
        Uri uri;
        if (!HasSettings()) throw new Exception("请填写接口地址、模型名称和 API Key。它们可以从模型平台的控制台或接口文档获取。");
        if (!Uri.TryCreate(endpoint.Text.Trim(), UriKind.Absolute, out uri) || (uri.Scheme != "https" && uri.Scheme != "http"))
            throw new Exception("接口地址必须是完整的 http:// 或 https:// 地址，请使用平台提供的 Base URL。");
        if (uri.AbsolutePath.TrimEnd('/').EndsWith("/chat/completions", StringComparison.OrdinalIgnoreCase))
            throw new Exception("这里填写 API 基础地址，不包含末尾的 /chat/completions。");
        var entry = new Dictionary<string, object> { { "id", "my-vision-model" }, { "channel", "openai" }, { "type", "chat" }, { "supports_vision", true }, { "model", model.Text.Trim() }, { "base_url", endpoint.Text.Trim().TrimEnd('/') }, { "api_key", key.Text.Trim() } };
        var config = new Dictionary<string, object> { { "default", "my-vision-model" }, { "fallback", "my-vision-model" }, { "fast", "my-vision-model" }, { "vision", "my-vision-model" }, { "models", new[] { entry } } };
        string file = Path.Combine(service.AppDirectory, "models.json");
        string temporary = file + ".tmp";
        File.WriteAllText(temporary, new JavaScriptSerializer().Serialize(config), new UTF8Encoding(false));
        if (File.Exists(file)) File.Replace(temporary, file, file + ".bak");
        else File.Move(temporary, file);
    }

    void SetBusy(bool value) { busy = value; start.Enabled = !value; stop.Enabled = !value; }

    async Task StartApp(bool save)
    {
        if (busy) return;
        SetBusy(true);
        try
        {
            if (save)
            {
                if (service.Running && MessageBox.Show("保存配置需要重启服务。请先保存作答并等待生成、判卷完成。现在重启？", "更新模型配置", MessageBoxButtons.OKCancel) != DialogResult.OK) return;
                SaveSettings();
                await Task.Run(() => service.Stop());
            }
            status.Text = "正在启动，请稍候……";
            await Task.Run(() => service.Start());
            status.Text = "已启动：" + service.Url + "/exam\n页面能打开不代表模型连接成功，请用一页小 PDF 验证。";
            OpenPath(service.Url + "/exam");
        }
        catch (Exception ex) { status.Text = "未能完成操作，请根据提示处理后重试。"; MessageBox.Show(ex.Message, "成考助手", MessageBoxButtons.OK, MessageBoxIcon.Information); }
        finally { SetBusy(false); }
    }

    void OpenPath(string path)
    {
        try { Process.Start(new ProcessStartInfo(path) { UseShellExecute = true }); }
        catch { MessageBox.Show("无法自动打开。请手动打开这个位置：\n" + path, "成考助手"); }
    }
}
