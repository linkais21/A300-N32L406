using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.IO.Ports;
using System.Net;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Xml;

[assembly: AssemblyTitle("A300 Production Tester")]
[assembly: AssemblyDescription("A300 production parameter writer and functional tester")]
[assembly: AssemblyCompany("A300")]
[assembly: AssemblyProduct("A300 Production Tester")]
[assembly: AssemblyVersion("1.5.0.0")]
[assembly: AssemblyFileVersion("1.5.0.0")]

namespace A300ProductionTester
{
    internal static class Program
    {
        [STAThread]
        private static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm());
        }
    }

    internal sealed class SerialClient : IDisposable
    {
        private readonly SerialPort _port = new SerialPort();
        private readonly object _commandLock = new object();
        private readonly object _responseLock = new object();
        private readonly AutoResetEvent _rxEvent = new AutoResetEvent(false);
        private readonly ResponseFramer _framer = new ResponseFramer(4096);
        private string _activeCommand = "";
        private string _matchedResponse = "";
        private bool _capturing;

        public event Action<string> DataReceived;

        public bool IsOpen { get { return _port.IsOpen; } }
        public string PortName { get { return _port.PortName; } }

        public void Open(string portName, int baudRate)
        {
            if (_port.IsOpen) _port.Close();
            _port.PortName = portName;
            _port.BaudRate = baudRate;
            _port.DataBits = 8;
            _port.Parity = Parity.None;
            _port.StopBits = StopBits.One;
            _port.Handshake = Handshake.None;
            _port.Encoding = Encoding.UTF8;
            _port.NewLine = "\r\n";
            _port.ReadTimeout = 500;
            _port.WriteTimeout = 1000;
            _port.DtrEnable = false;
            _port.RtsEnable = false;
            _port.DataReceived += PortDataReceived;
            _port.Open();
        }

        public void Close()
        {
            if (_port.IsOpen) _port.Close();
        }

        private void PortDataReceived(object sender, SerialDataReceivedEventArgs e)
        {
            try
            {
                string data = _port.ReadExisting();
                if (data.Length == 0) return;
                lock (_responseLock)
                {
                    IList<string> lines = _framer.Push(data);
                    if (_capturing && _matchedResponse.Length == 0)
                    {
                        foreach (string line in lines)
                        {
                            if (!ProductionReply.IsCorrelatedComplete(_activeCommand, line)) continue;
                            _matchedResponse = line;
                            break;
                        }
                    }
                }
                _rxEvent.Set();
                Action<string> handler = DataReceived;
                if (handler != null) handler(data);
            }
            catch { }
        }

        public string SendCommand(string command, int timeoutMs)
        {
            return SendCommandCore(command, timeoutMs, delegate
            {
                _port.Write(command.TrimEnd('\r', '\n') + "\r\n");
            });
        }

        public string SendCommandBytes(string commandKey, byte[] wireBytes, int timeoutMs)
        {
            if (wireBytes == null || wireBytes.Length == 0)
                throw new ArgumentException("命令字节不能为空", "wireBytes");
            return SendCommandCore(commandKey, timeoutMs, delegate
            {
                _port.Write(wireBytes, 0, wireBytes.Length);
            });
        }

        private string SendCommandCore(string command, int timeoutMs, Action write)
        {
            if (!_port.IsOpen) throw new InvalidOperationException("串口未连接");
            lock (_commandLock)
            {
                lock (_responseLock)
                {
                    _framer.Clear();
                    _activeCommand = command;
                    _matchedResponse = "";
                    _capturing = true;
                }

                while (_rxEvent.WaitOne(0)) { }
                write();

                DateTime deadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
                string response = "";
                while (DateTime.UtcNow < deadline)
                {
                    _rxEvent.WaitOne(120);
                    lock (_responseLock) response = _matchedResponse;
                    if (response.Length > 0) break;
                }

                lock (_responseLock)
                {
                    response = _matchedResponse;
                    _capturing = false;
                    _activeCommand = "";
                }
                return response;
            }
        }

        public void Dispose()
        {
            Close();
            _port.Dispose();
            _rxEvent.Dispose();
        }
    }

    internal sealed class IniStore
    {
        private readonly string _path;
        private readonly Dictionary<string, string> _values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        public IniStore(string path)
        {
            _path = path;
            Load();
        }

        private void Load()
        {
            if (!File.Exists(_path)) return;
            foreach (string raw in File.ReadAllLines(_path, Encoding.UTF8))
            {
                string line = raw.Trim();
                if (line.Length == 0 || line.StartsWith("#") || line.StartsWith(";")) continue;
                int p = line.IndexOf('=');
                if (p <= 0) continue;
                _values[line.Substring(0, p).Trim()] = line.Substring(p + 1).Trim();
            }
        }

        public string Get(string key, string defaultValue)
        {
            string value;
            return _values.TryGetValue(key, out value) ? value : defaultValue;
        }

        public void Set(string key, string value) { _values[key] = value ?? ""; }

        public void Save()
        {
            Directory.CreateDirectory(Path.GetDirectoryName(_path));
            List<string> lines = new List<string>();
            lines.Add("# A300 生产测试工具配置（UTF-8）");
            foreach (KeyValuePair<string, string> pair in _values) lines.Add(pair.Key + "=" + pair.Value);
            File.WriteAllLines(_path, lines.ToArray(), new UTF8Encoding(false));
        }
    }

    internal sealed class TestItem
    {
        public int Number;
        public string Code;
        public string Name;
        public string Parameter;
        public string Value;
        public int TimeoutSeconds;
        public bool Enabled;
        public string Detected;
        public string Result;
        public string Note;
        public string RawResponse;
        public string FailureReason;
        public string OperatorConfirmation;
    }

    internal sealed class RtkAccount
    {
        public string Host;
        public string Port;
        public string User;
        public string Password;
        public string Mount;
        public int SourceRow;
    }

    internal sealed class RecordSyncJob
    {
        public string OrderNo;
        public string SummaryPath;
        public string DetailPath;
        public bool ShareEnabled;
        public string SharePath;
        public bool FtpEnabled;
        public string FtpUrl;
        public string FtpUser;
        public string FtpPassword;
        public bool HttpEnabled;
        public string HttpUrl;
        public string HttpToken;
    }

    internal static class RtkExcelReader
    {
        public static List<RtkAccount> Read(string path)
        {
            if (!File.Exists(path)) throw new FileNotFoundException("RTK账号Excel文件不存在。", path);
            if (!string.Equals(Path.GetExtension(path), ".xlsx", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("仅支持 .xlsx 格式，请使用工具提供的示例文档填写。 ");

            using (ZipArchive archive = ZipFile.OpenRead(path))
            {
                List<string> shared = ReadSharedStrings(archive);
                string sheetPath = FirstWorksheetPath(archive);
                ZipArchiveEntry sheetEntry = FindEntry(archive, sheetPath);
                if (sheetEntry == null) throw new InvalidOperationException("Excel中未找到第一个工作表。 ");

                XmlDocument doc = LoadXml(sheetEntry);
                XmlNamespaceManager ns = new XmlNamespaceManager(doc.NameTable);
                ns.AddNamespace("x", "http://schemas.openxmlformats.org/spreadsheetml/2006/main");
                XmlNodeList rows = doc.SelectNodes("//x:sheetData/x:row", ns);
                Dictionary<string, int> headers = null;
                List<RtkAccount> result = new List<RtkAccount>();

                foreach (XmlNode row in rows)
                {
                    Dictionary<int, string> cells = ReadRow(row, ns, shared);
                    if (cells.Count == 0) continue;
                    if (headers == null)
                    {
                        headers = BuildHeaders(cells);
                        ValidateHeaders(headers);
                        continue;
                    }

                    int rowNumber;
                    if (!int.TryParse(Attribute(row, "r"), out rowNumber)) rowNumber = result.Count + 2;
                    RtkAccount item = new RtkAccount
                    {
                        Host = Cell(cells, Column(headers, "host")).Trim(),
                        Port = NormalizeIdentity(Cell(cells, Column(headers, "port"))),
                        User = Cell(cells, Column(headers, "user")).Trim(),
                        Password = Cell(cells, Column(headers, "password")).Trim(),
                        Mount = Cell(cells, Column(headers, "mount")).Trim(),
                        SourceRow = rowNumber
                    };
                    if (item.Host.Length == 0 && item.Port.Length == 0 && item.User.Length == 0 && item.Password.Length == 0 && item.Mount.Length == 0) continue;
                    ValidateItem(item);
                    result.Add(item);
                }

                if (headers == null) throw new InvalidOperationException("Excel没有有效表头。 ");
                if (result.Count == 0) throw new InvalidOperationException("Excel没有可导入的RTK账号数据。 ");
                return result;
            }
        }

        private static void ValidateItem(RtkAccount item)
        {
            int port;
            if (item.Host.Length == 0 || !int.TryParse(item.Port, out port) || port < 1 || port > 65535 || item.User.Length == 0 || item.Password.Length == 0 || item.Mount.Length == 0)
                throw new InvalidOperationException("Excel第" + item.SourceRow + "行RTK服务、端口、账号、密码和挂载点必须完整填写。 ");
            if (InvalidCommandValue(item.Host) || InvalidCommandValue(item.User) || InvalidCommandValue(item.Password) || InvalidCommandValue(item.Mount))
                throw new InvalidOperationException("Excel第" + item.SourceRow + "行RTK参数不能包含逗号、#号或换行。 ");
        }

        private static bool InvalidCommandValue(string value)
        {
            return value.IndexOf(',') >= 0 || value.IndexOf('#') >= 0 || value.IndexOf('\r') >= 0 || value.IndexOf('\n') >= 0;
        }

        private static void ValidateHeaders(Dictionary<string, int> headers)
        {
            foreach (string key in new[] { "host", "port", "user", "password", "mount" })
                if (!headers.ContainsKey(key)) throw new InvalidOperationException("Excel缺少必填列：" + HeaderDisplayName(key));
        }

        private static string HeaderDisplayName(string key)
        {
            if (key == "host") return "RTK服务IP/域名";
            if (key == "port") return "RTK端口";
            if (key == "user") return "RTK账号";
            if (key == "password") return "RTK密码";
            return "RTK挂载点";
        }

        private static Dictionary<string, int> BuildHeaders(Dictionary<int, string> cells)
        {
            Dictionary<string, int> result = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            foreach (KeyValuePair<int, string> cell in cells)
            {
                string key = HeaderKey(cell.Value);
                if (key.Length > 0 && !result.ContainsKey(key)) result[key] = cell.Key;
            }
            return result;
        }

        private static string HeaderKey(string text)
        {
            string value = Regex.Replace((text ?? "").Trim().ToUpperInvariant(), @"[\s_（）()]+", "");
            if (value == "RTK服务IP/域名" || value == "RTK服务IP" || value == "RTK域名" || value == "服务IP/域名" || value == "HOST") return "host";
            if (value == "RTK端口" || value == "端口" || value == "PORT") return "port";
            if (value == "RTK账号" || value == "差分账号" || value == "USER" || value == "USERNAME") return "user";
            if (value == "RTK密码" || value == "差分密码" || value == "PASSWORD") return "password";
            if (value == "RTK挂载点" || value == "挂载点" || value == "MOUNT" || value == "MOUNTPOINT") return "mount";
            return "";
        }

        private static int Column(Dictionary<string, int> headers, string key)
        {
            int value;
            return headers.TryGetValue(key, out value) ? value : -1;
        }

        private static string Cell(Dictionary<int, string> cells, int column)
        {
            string value;
            return column >= 0 && cells.TryGetValue(column, out value) ? value : "";
        }

        private static Dictionary<int, string> ReadRow(XmlNode row, XmlNamespaceManager ns, List<string> shared)
        {
            Dictionary<int, string> result = new Dictionary<int, string>();
            foreach (XmlNode cell in row.SelectNodes("x:c", ns))
            {
                int column = ColumnIndex(Attribute(cell, "r"));
                if (column < 0) continue;
                string type = Attribute(cell, "t");
                string value = "";
                if (type == "inlineStr")
                {
                    foreach (XmlNode t in cell.SelectNodes("x:is//x:t", ns)) value += t.InnerText;
                }
                else
                {
                    XmlNode v = cell.SelectSingleNode("x:v", ns);
                    value = v == null ? "" : v.InnerText;
                    int index;
                    if (type == "s" && int.TryParse(value, out index) && index >= 0 && index < shared.Count) value = shared[index];
                }
                result[column] = value;
            }
            return result;
        }

        private static List<string> ReadSharedStrings(ZipArchive archive)
        {
            List<string> result = new List<string>();
            ZipArchiveEntry entry = FindEntry(archive, "xl/sharedStrings.xml");
            if (entry == null) return result;
            XmlDocument doc = LoadXml(entry);
            XmlNamespaceManager ns = new XmlNamespaceManager(doc.NameTable);
            ns.AddNamespace("x", "http://schemas.openxmlformats.org/spreadsheetml/2006/main");
            foreach (XmlNode item in doc.SelectNodes("//x:si", ns))
            {
                StringBuilder text = new StringBuilder();
                foreach (XmlNode t in item.SelectNodes(".//x:t", ns)) text.Append(t.InnerText);
                result.Add(text.ToString());
            }
            return result;
        }

        private static string FirstWorksheetPath(ZipArchive archive)
        {
            ZipArchiveEntry workbook = FindEntry(archive, "xl/workbook.xml");
            ZipArchiveEntry relations = FindEntry(archive, "xl/_rels/workbook.xml.rels");
            if (workbook == null || relations == null) return "xl/worksheets/sheet1.xml";
            XmlDocument bookDoc = LoadXml(workbook);
            XmlNamespaceManager bookNs = new XmlNamespaceManager(bookDoc.NameTable);
            bookNs.AddNamespace("x", "http://schemas.openxmlformats.org/spreadsheetml/2006/main");
            bookNs.AddNamespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships");
            XmlNode sheet = bookDoc.SelectSingleNode("//x:sheets/x:sheet[1]", bookNs);
            if (sheet == null) return "xl/worksheets/sheet1.xml";
            string id = Attribute(sheet, "id", "http://schemas.openxmlformats.org/officeDocument/2006/relationships");

            XmlDocument relDoc = LoadXml(relations);
            XmlNamespaceManager relNs = new XmlNamespaceManager(relDoc.NameTable);
            relNs.AddNamespace("r", "http://schemas.openxmlformats.org/package/2006/relationships");
            XmlNode rel = relDoc.SelectSingleNode("//r:Relationship[@Id='" + id + "']", relNs);
            string target = rel == null ? "worksheets/sheet1.xml" : Attribute(rel, "Target");
            if (target.StartsWith("/")) return target.TrimStart('/');
            return "xl/" + target.Replace('\\', '/').TrimStart('/');
        }

        private static XmlDocument LoadXml(ZipArchiveEntry entry)
        {
            XmlDocument doc = new XmlDocument();
            using (Stream stream = entry.Open()) doc.Load(stream);
            return doc;
        }

        private static ZipArchiveEntry FindEntry(ZipArchive archive, string path)
        {
            foreach (ZipArchiveEntry entry in archive.Entries)
                if (string.Equals(entry.FullName, path, StringComparison.OrdinalIgnoreCase)) return entry;
            return null;
        }

        private static string Attribute(XmlNode node, string name)
        {
            return Attribute(node, name, "");
        }

        private static string Attribute(XmlNode node, string name, string namespaceUri)
        {
            if (node == null || node.Attributes == null) return "";
            XmlAttribute attribute = namespaceUri.Length == 0 ? node.Attributes[name] : node.Attributes[name, namespaceUri];
            return attribute == null ? "" : attribute.Value;
        }

        private static int ColumnIndex(string cellReference)
        {
            int value = 0;
            int count = 0;
            foreach (char c in cellReference)
            {
                if (!char.IsLetter(c)) break;
                value = value * 26 + (char.ToUpperInvariant(c) - 'A' + 1);
                count++;
            }
            return count == 0 ? -1 : value - 1;
        }

        private static string NormalizeIdentity(string value)
        {
            string text = (value ?? "").Trim();
            decimal number;
            if ((text.IndexOf('E') >= 0 || text.IndexOf('e') >= 0 || text.EndsWith(".0")) && decimal.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out number))
                return decimal.Truncate(number).ToString("0", CultureInfo.InvariantCulture);
            return text;
        }
    }

    internal sealed class MainForm : Form
    {
        private const string TesterVersion = "1.5.0";
        private readonly SerialClient _serial = new SerialClient();
        private readonly IniStore _settings;
        private readonly string _baseDir = AppDomain.CurrentDomain.BaseDirectory;
        private readonly ComboBox _ports = new ComboBox();
        private readonly ComboBox _baud = new ComboBox();
        private readonly Button _connect = new Button();
        private readonly Label _connectionState = new Label();
        private readonly TextBox _log = new TextBox();
        private readonly TextBox _customCommand = new TextBox();
        private readonly Button _sendCustom = new Button();
        private readonly TabControl _tabs = new TabControl();
        private readonly DataGridView _grid = new DataGridView();
        private readonly Dictionary<string, TextBox> _fields = new Dictionary<string, TextBox>();
        private readonly Dictionary<int, TestItem> _tests = new Dictionary<int, TestItem>();
        private readonly Label _summary = new Label();
        private readonly CheckBox _syncImeiTerminal = new CheckBox();
        private readonly CheckBox _scanAutoWorkflow = new CheckBox();
        private readonly Label _workflowState = new Label();
        private readonly Label _recordState = new Label();
        private readonly CheckBox _shareEnabled = new CheckBox();
        private readonly TextBox _sharePath = new TextBox();
        private readonly CheckBox _ftpEnabled = new CheckBox();
        private readonly TextBox _ftpUrl = new TextBox();
        private readonly TextBox _ftpUser = new TextBox();
        private readonly TextBox _ftpPassword = new TextBox();
        private readonly CheckBox _httpEnabled = new CheckBox();
        private readonly TextBox _httpUrl = new TextBox();
        private readonly TextBox _httpToken = new TextBox();
        private readonly Dictionary<string, CheckBox> _rtkWriteChecks = new Dictionary<string, CheckBox>();
        private readonly List<RtkAccount> _rtkAccounts = new List<RtkAccount>();
        private readonly Label _rtkImportState = new Label();
        private string _rtkExcelPath = "";
        private string _rtkExcelFingerprint = "";
        private int _rtkNextIndex;
        private int _pendingRtkIndex = -1;
        private RtkAccount _pendingRtkAccount;
        private bool _syncingRtkChecks;
        private volatile bool _busy;
        private string _latestParam = "";
        private double _latestCarVoltage = -1;
        private string _latestImei = "";
        private string _firmwareFullVersion = "";
        private string _firmwareSemanticVersion = "";
        private string _factoryCapabilityVersion = "";
        private string _latestCapabilityResponse = "";
        private FactoryCapabilities _factoryCapabilities;
        private volatile bool _relayTestMayBeLow;
        private const int GsensorDeltaThreshold = 30;
        private readonly object _recordLock = new object();
        private readonly Dictionary<string, string> _recordParameters = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, string> _recordWriteResults = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        private DateTime _recordStartedAt;
        private string _recordTerminalId = "";
        private string _recordImeiInput = "";
        private string _recordWriteSummary = "未执行参数写入";
        private string _activeOrderNo = "";
        private string _activeSummaryPath = "";
        private string _activeDetailPath = "";
        private bool _orderReady;
        private readonly object _recordFileLock = new object();
        private readonly object _syncLock = new object();
        private RecordSyncJob _pendingSyncJob;
        private bool _syncWorkerRunning;

        public MainForm()
        {
            Text = "A300 生产参数写入与功能测试工具 V1.5.0";
            Width = 1280;
            Height = 960;
            MinimumSize = new Size(1180, 820);
            StartPosition = FormStartPosition.CenterScreen;
            Font = new Font("Microsoft YaHei UI", 9F);

            _settings = new IniStore(Path.Combine(_baseDir, "config", "a300_tester.ini"));
            BuildUi();
            LoadSettingsToUi();
            ReloadSavedRtkExcel();
            RefreshPorts();
            _serial.DataReceived += SerialDataReceived;
            FormClosing += MainFormClosing;
            Shown += delegate { _fields["identity"].Focus(); };
        }

        private void BuildUi()
        {
            Panel top = new Panel { Dock = DockStyle.Top, Height = 48, Padding = new Padding(8) };
            Controls.Add(top);
            top.Controls.Add(new Label { Text = "串口", AutoSize = true, Location = new Point(10, 15) });
            _ports.SetBounds(50, 10, 105, 26);
            _ports.DropDownStyle = ComboBoxStyle.DropDownList;
            top.Controls.Add(_ports);
            Button refresh = new Button { Text = "刷新", Location = new Point(160, 9), Size = new Size(58, 28) };
            refresh.Click += delegate { RefreshPorts(); };
            top.Controls.Add(refresh);
            top.Controls.Add(new Label { Text = "波特率", AutoSize = true, Location = new Point(230, 15) });
            _baud.SetBounds(285, 10, 90, 26);
            _baud.Items.AddRange(new object[] { "115200", "9600", "57600" });
            _baud.DropDownStyle = ComboBoxStyle.DropDownList;
            _baud.SelectedIndex = 0;
            top.Controls.Add(_baud);
            _connect.Text = "连接设备";
            _connect.SetBounds(385, 9, 95, 28);
            _connect.Click += ConnectClicked;
            top.Controls.Add(_connect);
            _connectionState.Text = "● 未连接";
            _connectionState.ForeColor = Color.Firebrick;
            _connectionState.AutoSize = true;
            _connectionState.Location = new Point(495, 15);
            top.Controls.Add(_connectionState);

            top.Controls.Add(new Label { Text = "订单号", AutoSize = true, Location = new Point(605, 15), Font = new Font(Font, FontStyle.Bold) });
            TextBox orderNo = new TextBox { MaxLength = 64, ReadOnly = true, BackColor = Color.FromArgb(245, 248, 252) };
            orderNo.SetBounds(660, 10, 115, 27);
            top.Controls.Add(orderNo);
            _fields["order_no"] = orderNo;
            Button createOrder = new Button { Text = "新建", Location = new Point(780, 9), Size = new Size(48, 29) };
            createOrder.Click += delegate { CreateOrder(); };
            top.Controls.Add(createOrder);
            Button loadOrder = new Button { Text = "加载", Location = new Point(832, 9), Size = new Size(48, 29) };
            loadOrder.Click += delegate { LoadExistingOrder(); };
            top.Controls.Add(loadOrder);
            Label hint = new Label { Text = "A300 调试口：PA9(TX) / PA10(RX)，115200 8N1", ForeColor = Color.DimGray, AutoSize = true, Anchor = AnchorStyles.Top | AnchorStyles.Right };
            hint.Location = new Point(890, 15);
            top.Controls.Add(hint);

            _tabs.Dock = DockStyle.Fill;
            Controls.Add(_tabs);
            _tabs.TabPages.Add(BuildParameterTab());
            _tabs.TabPages.Add(BuildRecordTab());
            _tabs.TabPages.Add(BuildLogTab());
            Control storage = BuildStoragePanel();
            Controls.Add(storage);
            storage.BringToFront();
            top.BringToFront();
        }

        private TabPage BuildParameterTab()
        {
            TabPage page = new TabPage("一、参数写入");
            TableLayoutPanel root = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2, Margin = new Padding(0), Padding = new Padding(0) };
            root.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            root.RowStyles.Add(new RowStyle(SizeType.Absolute, 400));
            root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            page.Controls.Add(root);

            TableLayoutPanel table = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(16), ColumnCount = 4, RowCount = 12 };
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 180));
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 180));
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            root.Controls.Add(table, 0, 0);

            AddField(table, 0, "主平台 IP/域名", "main_ip", "119.147.205.85", "主平台端口", "main_port", "9999");
            AddField(table, 1, "副平台 IP/域名", "backup_ip", "", "副平台端口", "backup_port", "0");
            AddField(table, 2, "APN", "apn", "CMIOT", "RTK 服务 IP/域名", "rtk_ip", "", "service");
            AddField(table, 3, "APN 用户名", "apn_user", "", "RTK 端口", "rtk_port", "", "port");
            AddField(table, 4, "APN 密码", "apn_pass", "", "RTK 账号", "rtk_user", "", "user");
            AddField(table, 5, "ACC ON 上报间隔(秒)", "acc_on_interval", "30", "RTK 密码", "rtk_pass", "", "password");
            AddField(table, 6, "ACC OFF 上报间隔(秒)", "acc_off_interval", "180", "RTK 挂载点", "rtk_mount", "", "mount");
            AddModelAndRtkImportField(table, 7);
            AddIdentityField(table, 8);
            table.RowStyles.Add(new RowStyle(SizeType.Absolute, 40));
            table.RowStyles.Add(new RowStyle(SizeType.Absolute, 0));
            table.RowStyles.Add(new RowStyle(SizeType.Absolute, 0));

            Button read = new Button { Text = "读取设备参数", Height = 36, Dock = DockStyle.Fill };
            read.Click += delegate { RunWorker(ReadParameters); };
            table.Controls.Add(read, 0, 9);
            table.SetColumnSpan(read, 2);
            Button write = new Button { Text = "写入全部参数并复检", Height = 36, Dock = DockStyle.Fill, BackColor = Color.FromArgb(36, 125, 80), ForeColor = Color.White };
            write.Click += delegate { RunWorker(WriteAllParameters); };
            table.Controls.Add(write, 2, 9);
            table.SetColumnSpan(write, 2);

            Panel testArea = BuildTestArea();
            root.Controls.Add(testArea, 0, 1);
            return page;
        }

        private void AddIdentityField(TableLayoutPanel table, int row)
        {
            table.RowStyles.Add(new RowStyle(SizeType.Absolute, 40));
            table.Controls.Add(new Label { Text = "写入IMEI/终端ID", AutoSize = true, Anchor = AnchorStyles.Left, Font = new Font(Font, FontStyle.Bold) }, 0, row);
            Panel panel = new Panel { Dock = DockStyle.Fill, Margin = new Padding(3, 0, 14, 0), BackColor = Color.FromArgb(235, 245, 255) };
            TextBox identity = new TextBox { Font = new Font("Consolas", 13F, FontStyle.Bold), MaxLength = 11 };
            identity.SetBounds(0, 4, 285, 30);
            identity.KeyDown += IdentityKeyDown;
            panel.Controls.Add(identity);
            _fields["identity"] = identity;

            _syncImeiTerminal.Text = "IMEI同步其后11位终端ID";
            _syncImeiTerminal.AutoSize = true;
            _syncImeiTerminal.Location = new Point(300, 9);
            _syncImeiTerminal.CheckedChanged += delegate
            {
                identity.MaxLength = _syncImeiTerminal.Checked ? 15 : 11;
                SetWorkflowState(_syncImeiTerminal.Checked ? "请输入15位IMEI" : "请输入自定义11位终端ID", Color.DimGray);
                identity.SelectAll();
                identity.Focus();
            };
            panel.Controls.Add(_syncImeiTerminal);

            _scanAutoWorkflow.Text = "回车后自动写入并测试";
            _scanAutoWorkflow.AutoSize = true;
            _scanAutoWorkflow.Checked = true;
            _scanAutoWorkflow.Location = new Point(515, 9);
            panel.Controls.Add(_scanAutoWorkflow);

            Button start = new Button { Text = "写入并测试", Location = new Point(700, 4), Size = new Size(115, 31), BackColor = Color.FromArgb(30, 105, 180), ForeColor = Color.White };
            start.Click += delegate { StartIdentityWorkflow(true); };
            panel.Controls.Add(start);

            _workflowState.Text = "等待输入或扫码";
            _workflowState.AutoSize = true;
            _workflowState.Location = new Point(830, 10);
            _workflowState.ForeColor = Color.DimGray;
            panel.Controls.Add(_workflowState);

            table.Controls.Add(panel, 1, row);
            table.SetColumnSpan(panel, 3);
        }

        private void AddField(TableLayoutPanel table, int row, string label1, string key1, string def1, string label2, string key2, string def2)
        {
            AddField(table, row, label1, key1, def1, label2, key2, def2, null);
        }

        private void AddField(TableLayoutPanel table, int row, string label1, string key1, string def1, string label2, string key2, string def2, string rtkCheckKey)
        {
            table.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
            table.Controls.Add(new Label { Text = label1, AutoSize = true, Anchor = AnchorStyles.Left }, 0, row);
            TextBox box1 = new TextBox { Dock = DockStyle.Fill, Text = def1, Margin = new Padding(3, 5, 14, 2) };
            table.Controls.Add(box1, 1, row);
            _fields[key1] = box1;
            if (rtkCheckKey == null)
            {
                table.Controls.Add(new Label { Text = label2, AutoSize = true, Anchor = AnchorStyles.Left }, 2, row);
            }
            else
            {
                CheckBox check = new CheckBox { Text = label2, AutoSize = true, Anchor = AnchorStyles.Left, Checked = false, Tag = rtkCheckKey };
                check.CheckedChanged += RtkWriteCheckChanged;
                _rtkWriteChecks[rtkCheckKey] = check;
                table.Controls.Add(check, 2, row);
            }
            TextBox box2 = new TextBox { Dock = DockStyle.Fill, Text = def2, Margin = new Padding(3, 5, 14, 2) };
            table.Controls.Add(box2, 3, row);
            _fields[key2] = box2;
        }

        private void AddModelAndRtkImportField(TableLayoutPanel table, int row)
        {
            table.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
            table.Controls.Add(new Label { Text = "终端型号", AutoSize = true, Anchor = AnchorStyles.Left, Font = new Font(Font, FontStyle.Bold) }, 0, row);
            TextBox model = new TextBox { Dock = DockStyle.Fill, Text = "T360-A300", MaxLength = 20, Margin = new Padding(3, 5, 14, 2) };
            table.Controls.Add(model, 1, row);
            _fields["terminal_model"] = model;

            table.Controls.Add(new Label { Text = "RTK账号Excel", AutoSize = true, Anchor = AnchorStyles.Left, Font = new Font(Font, FontStyle.Bold) }, 2, row);
            Panel panel = new Panel { Dock = DockStyle.Fill, Margin = new Padding(3, 0, 14, 0) };
            Button import = new Button { Text = "导入", Location = new Point(0, 3), Size = new Size(68, 30) };
            import.Click += delegate { ImportRtkExcel(); };
            panel.Controls.Add(import);
            Button clear = new Button { Text = "清除", Location = new Point(74, 3), Size = new Size(68, 30) };
            clear.Click += delegate { ClearRtkExcel(); };
            panel.Controls.Add(clear);
            Button sample = new Button { Text = "示例文档", Location = new Point(148, 3), Size = new Size(88, 30) };
            sample.Click += delegate { OpenRtkExcelTemplate(); };
            panel.Controls.Add(sample);
            _rtkImportState.Text = "未导入（可手工填写RTK参数）";
            _rtkImportState.AutoSize = true;
            _rtkImportState.Location = new Point(244, 10);
            _rtkImportState.ForeColor = Color.DimGray;
            panel.Controls.Add(_rtkImportState);
            table.Controls.Add(panel, 3, row);
        }

        private void RtkWriteCheckChanged(object sender, EventArgs e)
        {
            if (_syncingRtkChecks) return;
            CheckBox changed = (CheckBox)sender;
            SetRtkWriteEnabled(changed.Checked);
        }

        private void SetRtkWriteEnabled(bool enabled)
        {
            _syncingRtkChecks = true;
            foreach (CheckBox check in _rtkWriteChecks.Values) check.Checked = enabled;
            _syncingRtkChecks = false;
            Color color = enabled ? SystemColors.Window : Color.FromArgb(242, 242, 242);
            foreach (string key in new[] { "rtk_ip", "rtk_port", "rtk_user", "rtk_pass", "rtk_mount" })
                if (_fields.ContainsKey(key)) _fields[key].BackColor = color;
        }

        private void IdentityKeyDown(object sender, KeyEventArgs e)
        {
            if (e.KeyCode != Keys.Enter) return;
            e.SuppressKeyPress = true;
            e.Handled = true;
            StartIdentityWorkflow(false);
        }

        private void StartIdentityWorkflow(bool forceStart)
        {
            string orderNo = _fields["order_no"].Text.Trim();
            if (!_orderReady || !ValidOrderNumber(orderNo))
            {
                SetWorkflowState("请先新建或加载订单", Color.Firebrick);
                return;
            }
            string scanned = _fields["identity"].Text.Trim();
            bool syncImei = _syncImeiTerminal.Checked;
            Match id = Regex.Match(scanned, syncImei ? @"^\d{15}$" : @"^\d{11}$");
            if (!id.Success)
            {
                SetWorkflowState(syncImei ? "勾选同步时必须输入15位IMEI" : "未勾选同步时必须输入11位终端ID", Color.Firebrick);
                _fields["identity"].SelectAll();
                _fields["identity"].Focus();
                return;
            }

            if (_busy)
            {
                SetWorkflowState("上一台设备仍在处理中", Color.DarkOrange);
                return;
            }

            string rtkError;
            if (!ApplyImportedRtk(scanned, out rtkError))
            {
                SetWorkflowState(rtkError, Color.Firebrick);
                _fields["identity"].SelectAll();
                _fields["identity"].Focus();
                return;
            }

            SaveUiSettings();
            SetWorkflowState("已录入：" + scanned, Color.FromArgb(30, 105, 180));

            if (forceStart || _scanAutoWorkflow.Checked)
                RunWorker(WriteParametersAndRunTests);
            else
                _fields["identity"].Focus();
        }

        private void ImportRtkExcel()
        {
            using (OpenFileDialog dialog = new OpenFileDialog())
            {
                dialog.Title = "导入RTK差分账号Excel";
                dialog.Filter = "Excel工作簿 (*.xlsx)|*.xlsx";
                dialog.CheckFileExists = true;
                if (_rtkExcelPath.Length > 0 && File.Exists(_rtkExcelPath)) dialog.FileName = _rtkExcelPath;
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                try
                {
                    LoadRtkExcel(dialog.FileName, true);
                    SetRtkWriteEnabled(true);
                    SaveUiSettings();
                    MessageBox.Show("已按Excel顺序导入 " + _rtkAccounts.Count + " 条RTK账号，分配进度已重置。\r\n下一台扫码设备将使用Excel第2行账号。", "RTK账号导入成功", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    _fields["identity"].Focus();
                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.Message, "RTK账号导入失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
            }
        }

        private void LoadRtkExcel(string path, bool resetProgress)
        {
            List<RtkAccount> accounts = RtkExcelReader.Read(path);
            _rtkAccounts.Clear();
            _rtkAccounts.AddRange(accounts);
            _rtkExcelPath = Path.GetFullPath(path);
            _rtkExcelFingerprint = RtkExcelFingerprint(_rtkExcelPath);
            _pendingRtkAccount = null;
            _pendingRtkIndex = -1;
            int savedIndex;
            bool sameFile = _settings.Get("rtk_excel_fingerprint", "") == _rtkExcelFingerprint;
            if (resetProgress || !sameFile || !int.TryParse(_settings.Get("rtk_excel_next_index", "0"), out savedIndex))
            {
                _rtkNextIndex = 0;
            }
            else
            {
                _rtkNextIndex = Math.Max(0, Math.Min(savedIndex, _rtkAccounts.Count));
            }
            UpdateRtkImportState();
            if (resetProgress) SetWorkflowState("RTK账号已导入，将从第1条开始顺序分配", Color.SeaGreen);
        }

        private void ReloadSavedRtkExcel()
        {
            string path = _settings.Get("rtk_excel_path", "");
            if (path.Length == 0) return;
            try { LoadRtkExcel(path, false); }
            catch
            {
                _rtkExcelPath = path;
                _rtkImportState.Text = "上次导入文件不可用，请重新导入";
                _rtkImportState.ForeColor = Color.Firebrick;
            }
        }

        private void ClearRtkExcel()
        {
            _rtkAccounts.Clear();
            _rtkExcelPath = "";
            _rtkExcelFingerprint = "";
            _rtkNextIndex = 0;
            _pendingRtkIndex = -1;
            _pendingRtkAccount = null;
            ClearRtkFields();
            SetRtkWriteEnabled(false);
            _rtkImportState.Text = "未导入（可手工填写RTK参数）";
            _rtkImportState.ForeColor = Color.DimGray;
            SaveUiSettings();
            _fields["identity"].Focus();
        }

        private void OpenRtkExcelTemplate()
        {
            string path = Path.Combine(_baseDir, "templates", "RTK差分账号导入示例.xlsx");
            if (!File.Exists(path))
            {
                MessageBox.Show("未找到示例文档：\r\n" + path, "A300", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            try { System.Diagnostics.Process.Start(path); }
            catch (Exception ex) { MessageBox.Show(ex.Message, "打开示例文档失败", MessageBoxButtons.OK, MessageBoxIcon.Error); }
        }

        private bool ApplyImportedRtk(string scanned, out string error)
        {
            error = "";
            if (!RtkWriteEnabled()) return true;
            if (_rtkExcelPath.Length == 0) return true;
            if (_rtkAccounts.Count == 0)
            {
                ClearRtkFields();
                error = "RTK账号Excel不可用，请重新导入";
                return false;
            }
            if (_pendingRtkAccount == null)
            {
                if (_rtkNextIndex >= _rtkAccounts.Count)
                {
                    ClearRtkFields();
                    error = "RTK账号已全部分配，请导入新的Excel";
                    return false;
                }
                _pendingRtkIndex = _rtkNextIndex;
                _pendingRtkAccount = _rtkAccounts[_pendingRtkIndex];
            }
            RtkAccount account = _pendingRtkAccount;
            _fields["rtk_ip"].Text = account.Host;
            _fields["rtk_port"].Text = account.Port;
            _fields["rtk_user"].Text = account.User;
            _fields["rtk_pass"].Text = account.Password;
            _fields["rtk_mount"].Text = account.Mount;
            _rtkImportState.Text = "当前分配第" + (_pendingRtkIndex + 1) + "/" + _rtkAccounts.Count + "条（Excel第" + account.SourceRow + "行）→ " + scanned;
            _rtkImportState.ForeColor = Color.FromArgb(30, 105, 180);
            return true;
        }

        private void CommitPendingRtkAccount()
        {
            if (_pendingRtkAccount == null || _pendingRtkIndex < 0) return;
            _rtkNextIndex = Math.Max(_rtkNextIndex, _pendingRtkIndex + 1);
            _pendingRtkAccount = null;
            _pendingRtkIndex = -1;
            _settings.Set("rtk_excel_next_index", _rtkNextIndex.ToString(CultureInfo.InvariantCulture));
            _settings.Set("rtk_excel_fingerprint", _rtkExcelFingerprint);
            _settings.Save();
            Ui(UpdateRtkImportState);
        }

        private void UpdateRtkImportState()
        {
            if (_rtkAccounts.Count == 0)
            {
                _rtkImportState.Text = "未导入（可手工填写RTK参数）";
                _rtkImportState.ForeColor = Color.DimGray;
                return;
            }
            if (_rtkNextIndex >= _rtkAccounts.Count)
            {
                _rtkImportState.Text = "已完成 " + _rtkAccounts.Count + "/" + _rtkAccounts.Count + " 条，账号已全部分配";
                _rtkImportState.ForeColor = Color.DarkOrange;
                return;
            }
            _rtkImportState.Text = "已完成 " + _rtkNextIndex + "/" + _rtkAccounts.Count + " 条；下一条为Excel第" + _rtkAccounts[_rtkNextIndex].SourceRow + "行";
            _rtkImportState.ForeColor = Color.SeaGreen;
        }

        private static string RtkExcelFingerprint(string path)
        {
            FileInfo file = new FileInfo(path);
            return file.Length.ToString(CultureInfo.InvariantCulture) + ":" + file.LastWriteTimeUtc.Ticks.ToString(CultureInfo.InvariantCulture);
        }

        private void ClearRtkFields()
        {
            foreach (string key in new[] { "rtk_ip", "rtk_port", "rtk_user", "rtk_pass", "rtk_mount" }) _fields[key].Clear();
        }

        private void SetWorkflowState(string text, Color color)
        {
            Ui(delegate
            {
                _workflowState.Text = text;
                _workflowState.ForeColor = color;
            });
        }

        private Panel BuildTestArea()
        {
            Panel area = new Panel { Dock = DockStyle.Fill };
            TableLayoutPanel layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 3, Margin = new Padding(0), Padding = new Padding(0) };
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 45));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 44));
            area.Controls.Add(layout);
            Panel settings = new Panel { Dock = DockStyle.Fill, Padding = new Padding(8) };
            layout.Controls.Add(settings, 0, 0);
            Button runAll = new Button { Text = "运行已选测试", Location = new Point(8, 8), Size = new Size(125, 29), BackColor = Color.FromArgb(30, 105, 180), ForeColor = Color.White };
            runAll.Click += delegate { RunWorker(RunAllTests); };
            settings.Controls.Add(runAll);
            Button runSelected = new Button { Text = "检测当前行", Location = new Point(143, 8), Size = new Size(105, 29) };
            runSelected.Click += delegate { RunSelectedTest(); };
            settings.Controls.Add(runSelected);
            Button pass = new Button { Text = "人工判定通过", Location = new Point(258, 8), Size = new Size(115, 29) };
            pass.Click += delegate { ManualResult("通过"); };
            settings.Controls.Add(pass);
            Button fail = new Button { Text = "人工判定不通过", Location = new Point(383, 8), Size = new Size(125, 29) };
            fail.Click += delegate { ManualResult("不通过"); };
            settings.Controls.Add(fail);

            _summary.Text = "未开始测试";
            _summary.Font = new Font(Font, FontStyle.Bold);
            _summary.AutoSize = true;
            _summary.Location = new Point(530, 15);
            settings.Controls.Add(_summary);

            ConfigureTestGrid();
            layout.Controls.Add(_grid, 0, 1);

            Panel bottom = new Panel { Dock = DockStyle.Fill, Padding = new Padding(8) };
            Button save = new Button { Text = "保存本机配置", Dock = DockStyle.Left, Width = 120 };
            save.Click += delegate { SaveUiSettings(); MessageBox.Show("配置已保存。", "A300"); };
            bottom.Controls.Add(save);
            Label autoRecord = new Label { Text = "测试记录：自动实时保存", Dock = DockStyle.Right, Width = 180, TextAlign = ContentAlignment.MiddleRight, ForeColor = Color.SeaGreen };
            bottom.Controls.Add(autoRecord);
            layout.Controls.Add(bottom, 0, 2);
            return area;
        }

        private void ConfigureTestGrid()
        {
            _grid.Dock = DockStyle.Fill;
            _grid.AllowUserToAddRows = false;
            _grid.AllowUserToDeleteRows = false;
            _grid.MultiSelect = false;
            _grid.SelectionMode = DataGridViewSelectionMode.FullRowSelect;
            _grid.AutoSizeRowsMode = DataGridViewAutoSizeRowsMode.AllCells;
            _grid.RowHeadersVisible = false;
            _grid.Columns.Add("No", "序号");
            _grid.Columns.Add("Code", "测试项");
            _grid.Columns.Add("Name", "测试项名称");
            _grid.Columns.Add(new DataGridViewCheckBoxColumn { Name = "Enabled", HeaderText = "全选/取消" });
            _grid.Columns.Add("Parameter", "参数");
            _grid.Columns.Add("Value", "值");
            _grid.Columns.Add("Timeout", "超时时间(s)");
            _grid.Columns.Add("Result", "状态");
            _grid.Columns.Add("Detected", "测试值");
            _grid.Columns.Add("Note", "备注");
            _grid.Columns[0].Width = 42;
            _grid.Columns[1].Width = 105;
            _grid.Columns[2].Width = 155;
            _grid.Columns[3].Width = 80;
            _grid.Columns[4].Width = 125;
            _grid.Columns[5].Width = 155;
            _grid.Columns[6].Width = 85;
            _grid.Columns[7].Width = 80;
            _grid.Columns[8].Width = 175;
            _grid.Columns[9].AutoSizeMode = DataGridViewAutoSizeColumnMode.Fill;
            for (int i = 0; i < _grid.Columns.Count; i++) _grid.Columns[i].ReadOnly = i != 3 && i != 5 && i != 6;
            _grid.CellFormatting += GridCellFormatting;
            _grid.ColumnHeaderMouseClick += GridColumnHeaderMouseClick;
            _grid.CurrentCellDirtyStateChanged += delegate { if (_grid.IsCurrentCellDirty) _grid.CommitEdit(DataGridViewDataErrorContexts.Commit); };

            AddTest(1, "VERSION", "程序版本检测", "版本号", _settings.Get("expected_version", "V1.281"), 30, "按固件语义版本匹配，不绑定构建时间");
            AddTest(2, "SERVER", "上线IP端口检测", "主平台IP:端口", "", 30, "写入后读取复检");
            AddTest(3, "TERMINAL_ID", "11位终端ID检测", "终端ID", "", 30, "按IMEI同步选项进行校验");
            AddTest(4, "SIM", "SIM卡插入检测", "ICCID", "非空", 90, "读取到ICCID信息即通过");
            AddTest(5, "CSQ", "GSM网络信号检测", "CSQ最小值", _settings.Get("csq_min", "10"), 90, "允许设置10-33");
            AddTest(6, "GPS", "GPS定位信号检测", "卫星-CN-HDOP-连续", _settings.Get("gps_threshold", "6-30-2.5-5"), 120, "必须接上天线且天线正常、有效定位、平均CN和HDOP连续达标");
            AddTest(7, "ACC", "ACC硬件线信号检测", "通断次数", "2", 30, "检测ACC有电、断电各两次");
            AddTest(8, "GSENSOR", "G-sensor震动功能检测", "传感器输出", "XYZ", 30, "震动整机检测数值输出");
            AddTest(9, "EXT_VOLT", "12V外电电压检测", "电压范围(V)", _settings.Get("voltage_range", "9-16"), 30, "检测外电输入电压");
            AddTest(10, "RELAY", "断油电功能测试", "低电平次数", "2", 30, "输出两次低电平，每次随后恢复");
            AddTest(11, "SOS", "SOS触发报警功能测试", "保持时间(s)", "2", 90, "等待SOS触发日志");
            AddTest(12, "TTS", "TTS语音播报功能测试", "播报文本", "生产测试语音正常", 30, "操作员确认声音");
            AddTest(13, "DEBUG_UART", "调试 UART 通信", "双向命令", "PARAM", 30, "PARAM 调试串口收发");
            AddTest(14, "RS485", "RS485串口功能测试", "本版本范围", "未测试", 30, "V1.281 不包含 RS485 生产测试");
        }

        private void AddTest(int number, string code, string name, string parameter, string defaultValue, int defaultTimeout, string note)
        {
            int timeout;
            if (!int.TryParse(_settings.Get("test_" + number + "_timeout", defaultTimeout.ToString()), out timeout)) timeout = defaultTimeout;
            string value = _settings.Get("test_" + number + "_value", defaultValue);
            if (number == 7 || number == 10) value = "2";
            if (number == 6 && (value ?? "").Split('-', ',', '/').Length < 4) value = "6-30-2.5-5";
            bool enabled = _settings.Get("test_" + number + "_enabled", "1") != "0";
            if (number == 14) enabled = false;
            TestItem item = new TestItem { Number = number, Code = code, Name = name, Parameter = parameter, Value = value, TimeoutSeconds = timeout, Enabled = enabled, Detected = "", Result = "等待", Note = note, RawResponse = "", FailureReason = "", OperatorConfirmation = "" };
            _tests[number] = item;
            _grid.Rows.Add(number, code, name, enabled, parameter, value, timeout, "等待", "", note);
        }

        private void GridColumnHeaderMouseClick(object sender, DataGridViewCellMouseEventArgs e)
        {
            if (e.ColumnIndex != 3) return;
            bool enableAll = false;
            foreach (DataGridViewRow row in _grid.Rows)
            {
                bool enabled = Convert.ToBoolean(row.Cells[3].Value);
                if (!enabled) { enableAll = true; break; }
            }
            foreach (DataGridViewRow row in _grid.Rows) row.Cells[3].Value = enableAll;
            SyncTestsFromGrid();
        }

        private void SyncTestsFromGrid()
        {
            Ui(delegate
            {
                for (int i = 1; i <= 14; i++)
                {
                    DataGridViewRow row = _grid.Rows[i - 1];
                    TestItem item = _tests[i];
                    item.Enabled = Convert.ToBoolean(row.Cells[3].Value);
                    item.Value = Convert.ToString(row.Cells[5].Value).Trim();
                    int timeout;
                    if (!int.TryParse(Convert.ToString(row.Cells[6].Value), out timeout) || timeout < 1) timeout = 30;
                    if (timeout > 300) timeout = 300;
                    item.TimeoutSeconds = timeout;
                    row.Cells[6].Value = timeout;
                }
            });
        }

        private void SyncTestPresetsFromParameters()
        {
            Ui(delegate
            {
                string server = _fields["main_ip"].Text.Trim();
                string port = _fields["main_port"].Text.Trim();
                if (server.Length > 0 && port.Length > 0) _grid.Rows[1].Cells[5].Value = server + ":" + port;
                string terminalId = ExpectedTerminalId();
                if (terminalId.Length > 0) _grid.Rows[2].Cells[5].Value = terminalId;
            });
            SyncTestsFromGrid();
        }

        private string TestValue(int number)
        {
            SyncTestsFromGrid();
            return _tests[number].Value;
        }

        private int TestTimeoutMs(int number)
        {
            SyncTestsFromGrid();
            return _tests[number].TimeoutSeconds * 1000;
        }

        private bool TestEnabled(int number)
        {
            return _tests[number].Enabled;
        }

        private TabPage BuildRecordTab()
        {
            TabPage page = new TabPage("二、订单配置");
            TableLayoutPanel table = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(24), ColumnCount = 4, RowCount = 3 };
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 180));
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 140));
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            table.RowStyles.Add(new RowStyle(SizeType.Absolute, 52));
            table.RowStyles.Add(new RowStyle(SizeType.Absolute, 52));
            table.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            page.Controls.Add(table);

            table.Controls.Add(new Label { Text = "订单配置", AutoSize = true, Anchor = AnchorStyles.Left, Font = new Font(Font, FontStyle.Bold) }, 0, 0);
            FlowLayoutPanel actions = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight, WrapContents = false };
            Button save = new Button { Text = "保存当前订单配置", Width = 145, Height = 30 };
            save.Click += delegate { SaveCurrentOrderProfile(true); };
            actions.Controls.Add(save);
            Button import = new Button { Text = "导入订单配置文件", Width = 145, Height = 30 };
            import.Click += delegate { ImportOrderProfile(); };
            actions.Controls.Add(import);
            Button openOrders = new Button { Text = "打开配置目录", Width = 120, Height = 30 };
            openOrders.Click += delegate { OpenDirectory(Path.Combine(_baseDir, "orders")); };
            actions.Controls.Add(openOrders);
            table.Controls.Add(actions, 1, 0);
            table.SetColumnSpan(actions, 3);

            table.Controls.Add(new Label { Text = "本机实时记录", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 1);
            TextBox localPath = new TextBox { Dock = DockStyle.Fill, ReadOnly = true, Text = Path.Combine(_baseDir, "records"), Margin = new Padding(3, 10, 12, 3) };
            table.Controls.Add(localPath, 1, 1);
            table.SetColumnSpan(localPath, 2);
            Button openRecords = new Button { Text = "打开记录目录", Dock = DockStyle.Fill, Margin = new Padding(3, 7, 3, 7) };
            openRecords.Click += delegate { OpenDirectory(Path.Combine(_baseDir, "records")); };
            table.Controls.Add(openRecords, 3, 1);
            Label note = new Label {
                Text = "订单必须通过顶部“新建”或“加载”激活。新建后在参数页填写写入参数并选择测试项目，再保存当前订单配置。",
                AutoSize = true, ForeColor = Color.DimGray, Anchor = AnchorStyles.Top | AnchorStyles.Left, Padding = new Padding(0, 16, 0, 0)
            };
            table.Controls.Add(note, 0, 2);
            table.SetColumnSpan(note, 4);
            return page;
        }

        private Control BuildStoragePanel()
        {
            Panel host = new Panel { Dock = DockStyle.Bottom, Height = 190, Padding = new Padding(8), BackColor = Color.FromArgb(242, 246, 250) };
            TableLayoutPanel root = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, RowCount = 3, Margin = new Padding(0), Padding = new Padding(0) };
            root.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 33.33F));
            root.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 33.33F));
            root.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 33.34F));
            root.RowStyles.Add(new RowStyle(SizeType.Absolute, 25));
            root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            root.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
            host.Controls.Add(root);

            Label title = new Label { Text = "产线管理员：测试记录同步配置（可同时启用）", AutoSize = true, Font = new Font(Font, FontStyle.Bold), ForeColor = Color.FromArgb(45, 65, 85), Anchor = AnchorStyles.Left };
            root.Controls.Add(title, 0, 0);
            root.SetColumnSpan(title, 3);
            root.Controls.Add(BuildShareStorageGroup(), 0, 1);
            root.Controls.Add(BuildFtpStorageGroup(), 1, 1);
            root.Controls.Add(BuildHttpStorageGroup(), 2, 1);

            Panel footer = new Panel { Dock = DockStyle.Fill };
            _recordState.Text = "记录将在写参开始后自动实时保存；远程目标由产线管理员在此配置";
            _recordState.Dock = DockStyle.Fill;
            _recordState.TextAlign = ContentAlignment.MiddleLeft;
            _recordState.ForeColor = Color.DimGray;
            footer.Controls.Add(_recordState);
            FlowLayoutPanel buttons = new FlowLayoutPanel { Dock = DockStyle.Right, Width = 250, FlowDirection = FlowDirection.LeftToRight, WrapContents = false, Padding = new Padding(0, 2, 0, 0) };
            Button save = new Button { Text = "保存同步配置", Width = 115, Height = 28 };
            save.Click += delegate { SaveUiSettings(); SetRecordState("同步配置已保存", Color.SeaGreen); };
            buttons.Controls.Add(save);
            Button test = new Button { Text = "测试同步", Width = 105, Height = 28 };
            test.Click += delegate { TestStorageConfiguration(); };
            buttons.Controls.Add(test);
            footer.Controls.Add(buttons);
            buttons.BringToFront();
            root.Controls.Add(footer, 0, 2);
            root.SetColumnSpan(footer, 3);
            return host;
        }

        private GroupBox BuildShareStorageGroup()
        {
            GroupBox group = new GroupBox { Text = "共享文件夹", Dock = DockStyle.Fill, Margin = new Padding(3, 0, 6, 2) };
            TableLayoutPanel table = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 3, Padding = new Padding(6, 2, 6, 4) };
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 72));
            table.RowStyles.Add(new RowStyle(SizeType.Absolute, 25));
            table.RowStyles.Add(new RowStyle(SizeType.Absolute, 31));
            table.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            group.Controls.Add(table);
            _shareEnabled.Text = "启用共享目录同步";
            _shareEnabled.AutoSize = true;
            _shareEnabled.Anchor = AnchorStyles.Left;
            table.Controls.Add(_shareEnabled, 0, 0);
            table.SetColumnSpan(_shareEnabled, 2);
            _sharePath.Dock = DockStyle.Fill;
            _sharePath.Margin = new Padding(0, 3, 6, 2);
            table.Controls.Add(_sharePath, 0, 1);
            Button browse = new Button { Text = "选择", Dock = DockStyle.Fill, Margin = new Padding(0, 1, 0, 1) };
            browse.Click += delegate { BrowseShareDirectory(); };
            table.Controls.Add(browse, 1, 1);
            Label hint = new Label { Text = @"本地目录或 \\服务器\共享目录", AutoSize = true, ForeColor = Color.DimGray, Anchor = AnchorStyles.Left };
            table.Controls.Add(hint, 0, 2);
            table.SetColumnSpan(hint, 2);
            return group;
        }

        private GroupBox BuildFtpStorageGroup()
        {
            GroupBox group = new GroupBox { Text = "FTP", Dock = DockStyle.Fill, Margin = new Padding(3, 0, 6, 2) };
            TableLayoutPanel table = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 4, RowCount = 3, Padding = new Padding(6, 2, 6, 4) };
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 40));
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 40));
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            table.RowStyles.Add(new RowStyle(SizeType.Absolute, 25));
            table.RowStyles.Add(new RowStyle(SizeType.Absolute, 31));
            table.RowStyles.Add(new RowStyle(SizeType.Absolute, 31));
            group.Controls.Add(table);
            _ftpEnabled.Text = "启用FTP同步";
            _ftpEnabled.AutoSize = true;
            _ftpEnabled.Anchor = AnchorStyles.Left;
            table.Controls.Add(_ftpEnabled, 0, 0);
            table.SetColumnSpan(_ftpEnabled, 4);
            table.Controls.Add(new Label { Text = "地址", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 1);
            _ftpUrl.Dock = DockStyle.Fill;
            _ftpUrl.Margin = new Padding(0, 3, 0, 2);
            table.Controls.Add(_ftpUrl, 1, 1);
            table.SetColumnSpan(_ftpUrl, 3);
            table.Controls.Add(new Label { Text = "账号", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 2);
            _ftpUser.Dock = DockStyle.Fill;
            _ftpUser.Margin = new Padding(0, 3, 6, 2);
            table.Controls.Add(_ftpUser, 1, 2);
            table.Controls.Add(new Label { Text = "密码", AutoSize = true, Anchor = AnchorStyles.Left }, 2, 2);
            _ftpPassword.Dock = DockStyle.Fill;
            _ftpPassword.UseSystemPasswordChar = true;
            _ftpPassword.Margin = new Padding(0, 3, 0, 2);
            table.Controls.Add(_ftpPassword, 3, 2);
            return group;
        }

        private GroupBox BuildHttpStorageGroup()
        {
            GroupBox group = new GroupBox { Text = "HTTP / HTTPS服务器", Dock = DockStyle.Fill, Margin = new Padding(3, 0, 3, 2) };
            TableLayoutPanel table = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 3, Padding = new Padding(6, 2, 6, 4) };
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 55));
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            table.RowStyles.Add(new RowStyle(SizeType.Absolute, 25));
            table.RowStyles.Add(new RowStyle(SizeType.Absolute, 31));
            table.RowStyles.Add(new RowStyle(SizeType.Absolute, 31));
            group.Controls.Add(table);
            _httpEnabled.Text = "启用HTTP/HTTPS同步";
            _httpEnabled.AutoSize = true;
            _httpEnabled.Anchor = AnchorStyles.Left;
            table.Controls.Add(_httpEnabled, 0, 0);
            table.SetColumnSpan(_httpEnabled, 2);
            table.Controls.Add(new Label { Text = "接口", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 1);
            _httpUrl.Dock = DockStyle.Fill;
            _httpUrl.Margin = new Padding(0, 3, 0, 2);
            table.Controls.Add(_httpUrl, 1, 1);
            table.Controls.Add(new Label { Text = "Token", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 2);
            _httpToken.Dock = DockStyle.Fill;
            _httpToken.UseSystemPasswordChar = true;
            _httpToken.Margin = new Padding(0, 3, 0, 2);
            table.Controls.Add(_httpToken, 1, 2);
            return group;
        }

        private static string[] OrderProfileFieldKeys()
        {
            return new[] {
                "main_ip", "main_port", "backup_ip", "backup_port", "terminal_model",
                "apn", "apn_user", "apn_pass", "acc_on_interval", "acc_off_interval",
                "rtk_ip", "rtk_port", "rtk_user", "rtk_pass", "rtk_mount"
            };
        }

        private void CreateOrder()
        {
            if (_busy) { MessageBox.Show("当前任务尚未完成，不能切换订单。", "订单"); return; }
            string orderNo;
            if (!PromptOrderNumber(out orderNo)) return;
            if (!ValidOrderNumber(orderNo))
            {
                MessageBox.Show("订单号必须为1-64位字母、数字、点、下划线或短横线，且不能包含连续两个点。", "新建订单", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            string path = Path.Combine(_baseDir, "orders", SafeFileName(orderNo) + ".ini");
            if (File.Exists(path))
            {
                MessageBox.Show("该订单已经存在，请使用“加载”选择已有订单。", "新建订单", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            ActivateOrder(orderNo);
            SaveCurrentOrderProfile(false);
            _tabs.SelectedIndex = 0;
            MessageBox.Show("订单已创建，当前屏幕参数作为初始配置。请检查或修改写入参数、选择测试项目，然后点击“保存当前订单配置”。", "新建订单");
        }

        private void LoadExistingOrder()
        {
            if (_busy) { MessageBox.Show("当前任务尚未完成，不能切换订单。", "订单"); return; }
            string dir = Path.Combine(_baseDir, "orders");
            Directory.CreateDirectory(dir);
            using (OpenFileDialog dialog = new OpenFileDialog())
            {
                dialog.InitialDirectory = dir;
                dialog.Filter = "订单配置 (*.ini)|*.ini";
                dialog.Title = "加载已有订单";
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                IniStore profile = new IniStore(dialog.FileName);
                string orderNo = profile.Get("order_no", Path.GetFileNameWithoutExtension(dialog.FileName)).Trim();
                if (!ValidOrderNumber(orderNo))
                {
                    MessageBox.Show("订单配置中的订单号无效。", "加载失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }
                LoadOrderProfile(dialog.FileName, orderNo, true);
                _tabs.SelectedIndex = 0;
            }
        }

        private bool PromptOrderNumber(out string orderNo)
        {
            orderNo = "";
            using (Form dialog = new Form())
            {
                dialog.Text = "新建订单";
                dialog.StartPosition = FormStartPosition.CenterParent;
                dialog.FormBorderStyle = FormBorderStyle.FixedDialog;
                dialog.MaximizeBox = false;
                dialog.MinimizeBox = false;
                dialog.ClientSize = new Size(420, 125);
                dialog.Controls.Add(new Label { Text = "订单号", AutoSize = true, Location = new Point(20, 25) });
                TextBox input = new TextBox { Location = new Point(85, 20), Width = 310, MaxLength = 64 };
                dialog.Controls.Add(input);
                Button ok = new Button { Text = "创建", DialogResult = DialogResult.OK, Location = new Point(235, 72), Width = 75 };
                Button cancel = new Button { Text = "取消", DialogResult = DialogResult.Cancel, Location = new Point(320, 72), Width = 75 };
                dialog.Controls.Add(ok);
                dialog.Controls.Add(cancel);
                dialog.AcceptButton = ok;
                dialog.CancelButton = cancel;
                if (dialog.ShowDialog(this) != DialogResult.OK) return false;
                orderNo = input.Text.Trim();
                return true;
            }
        }

        private void ActivateOrder(string orderNo)
        {
            _fields["order_no"].Text = orderNo;
            _fields["identity"].Clear();
            _orderReady = true;
            lock (_recordLock)
            {
                _activeOrderNo = "";
                _activeSummaryPath = "";
                _activeDetailPath = "";
                _recordTerminalId = "";
                _recordImeiInput = "";
                _recordParameters.Clear();
                _recordWriteResults.Clear();
                _recordWriteSummary = "未执行参数写入";
            }
            SetRecordState("当前订单：" + orderNo + "。请配置参数和测试项目。", Color.FromArgb(30, 105, 180));
        }

        private void SaveCurrentOrderProfile(bool showMessage)
        {
            string orderNo = Field("order_no");
            if (!_orderReady || !ValidOrderNumber(orderNo))
            {
                if (showMessage) MessageBox.Show("请先使用顶部“新建”或“加载”按钮选择订单。", "订单配置", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            SyncTestsFromGrid();
            string dir = Path.Combine(_baseDir, "orders");
            Directory.CreateDirectory(dir);
            string path = Path.Combine(dir, SafeFileName(orderNo) + ".ini");
            IniStore profile = new IniStore(path);
            profile.Set("order_no", orderNo);
            foreach (string key in OrderProfileFieldKeys()) profile.Set(key, Field(key));
            for (int i = 1; i <= 14; i++)
            {
                TestItem item = _tests[i];
                profile.Set("test_" + i + "_enabled", item.Enabled ? "1" : "0");
                profile.Set("test_" + i + "_value", item.Value);
                profile.Set("test_" + i + "_timeout", item.TimeoutSeconds.ToString(CultureInfo.InvariantCulture));
            }
            profile.Set("sync_imei_terminal", SyncImeiTerminalEnabled() ? "1" : "0");
            profile.Set("rtk_write_enabled", RtkWriteEnabled() ? "1" : "0");
            profile.Save();
            SetRecordState("订单配置已保存：" + path, Color.SeaGreen);
            if (showMessage) MessageBox.Show("订单配置已保存：\r\n" + path, "订单配置");
        }

        private void LoadOrderProfile(string path, string orderNo, bool showMessage)
        {
            ActivateOrder(orderNo);
            IniStore profile = new IniStore(path);
            foreach (string key in OrderProfileFieldKeys())
                if (_fields.ContainsKey(key)) _fields[key].Text = profile.Get(key, _fields[key].Text);
            for (int i = 1; i <= 14; i++)
            {
                bool enabled = profile.Get("test_" + i + "_enabled", _tests[i].Enabled ? "1" : "0") != "0";
                string value = profile.Get("test_" + i + "_value", _tests[i].Value);
                if (i == 6 && (value ?? "").Split('-', ',', '/').Length < 4) value = "6-30-2.5-5";
                int timeout;
                if (!int.TryParse(profile.Get("test_" + i + "_timeout", _tests[i].TimeoutSeconds.ToString()), out timeout) || timeout < 1) timeout = _tests[i].TimeoutSeconds;
                if (timeout > 300) timeout = 300;
                _grid.Rows[i - 1].Cells[3].Value = enabled;
                _grid.Rows[i - 1].Cells[5].Value = value;
                _grid.Rows[i - 1].Cells[6].Value = timeout;
            }
            _syncImeiTerminal.Checked = profile.Get("sync_imei_terminal", _syncImeiTerminal.Checked ? "1" : "0") == "1";
            SetRtkWriteEnabled(profile.Get("rtk_write_enabled", RtkWriteEnabled() ? "1" : "0") == "1");
            SyncTestsFromGrid();
            SetRecordState("已加载订单配置：" + orderNo, Color.SeaGreen);
            if (showMessage) MessageBox.Show("订单配置已加载：\r\n" + path, "订单配置");
        }

        private void ImportOrderProfile()
        {
            using (OpenFileDialog dialog = new OpenFileDialog())
            {
                dialog.Filter = "订单配置 (*.ini)|*.ini|所有文件 (*.*)|*.*";
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                IniStore imported = new IniStore(dialog.FileName);
                string orderNo = imported.Get("order_no", Field("order_no")).Trim();
                if (!ValidOrderNumber(orderNo))
                {
                    MessageBox.Show("配置文件没有有效的 order_no，且当前订单号无效。", "导入失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }
                string dir = Path.Combine(_baseDir, "orders");
                Directory.CreateDirectory(dir);
                string target = Path.Combine(dir, SafeFileName(orderNo) + ".ini");
                if (!string.Equals(Path.GetFullPath(dialog.FileName), Path.GetFullPath(target), StringComparison.OrdinalIgnoreCase))
                    File.Copy(dialog.FileName, target, true);
                IniStore normalized = new IniStore(target);
                normalized.Set("order_no", orderNo);
                normalized.Save();
                LoadOrderProfile(target, orderNo, true);
            }
        }

        private static bool ValidOrderNumber(string orderNo)
        {
            return Regex.IsMatch(orderNo ?? "", @"^[A-Za-z0-9._-]{1,64}$") && (orderNo ?? "").IndexOf("..", StringComparison.Ordinal) < 0;
        }

        private void BrowseShareDirectory()
        {
            using (FolderBrowserDialog dialog = new FolderBrowserDialog())
            {
                dialog.SelectedPath = _sharePath.Text.Trim();
                if (dialog.ShowDialog(this) == DialogResult.OK) _sharePath.Text = dialog.SelectedPath;
            }
        }

        private void TestStorageConfiguration()
        {
            if (!_shareEnabled.Checked && !_ftpEnabled.Checked && !_httpEnabled.Checked)
            {
                MessageBox.Show("请至少启用一个共享目录、FTP或HTTP服务器目标。", "存储配置", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            SaveUiSettings();
            string orderNo = ValidOrderNumber(Field("order_no")) ? Field("order_no") : "SYNC-TEST";
            string dir = Path.Combine(_baseDir, "records", "_同步测试", DateTime.Now.ToString("yyyyMMdd"));
            string stamp = DateTime.Now.ToString("yyyyMMdd_HHmmss_fff");
            string summary = Path.Combine(dir, stamp + "_同步测试_汇总.csv");
            string detail = Path.Combine(dir, stamp + "_同步测试_明细.csv");
            WriteAllLinesAtomic(summary, new[] { "订单号,时间,类型", JoinCsv(new[] { orderNo, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"), "存储配置测试" }) });
            WriteAllLinesAtomic(detail, new[] { "订单号,时间,说明", JoinCsv(new[] { orderNo, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"), "共享目录/FTP/HTTP连通性测试" }) });
            SetRecordState("本机测试文件已创建，正在验证远程同步...", Color.FromArgb(30, 105, 180));
            QueueRecordSync(orderNo, summary, detail);
        }

        private void OpenDirectory(string path)
        {
            try
            {
                Directory.CreateDirectory(path);
                System.Diagnostics.Process.Start(path);
            }
            catch (Exception ex) { MessageBox.Show(ex.Message, "打开目录失败", MessageBoxButtons.OK, MessageBoxIcon.Error); }
        }

        private void SetRecordState(string text, Color color)
        {
            Ui(delegate { _recordState.Text = text; _recordState.ForeColor = color; });
        }

        private TabPage BuildLogTab()
        {
            TabPage page = new TabPage("三、串口日志与手工命令");
            Panel command = new Panel { Dock = DockStyle.Top, Height = 47, Padding = new Padding(8) };
            command.Controls.Add(new Label { Text = "手工命令", AutoSize = true, Location = new Point(9, 15) });
            _customCommand.SetBounds(80, 9, 650, 27);
            _customCommand.Text = "PARAM#";
            command.Controls.Add(_customCommand);
            _sendCustom.Text = "发送";
            _sendCustom.SetBounds(740, 8, 75, 29);
            _sendCustom.Click += delegate { SendCustomCommand(); };
            command.Controls.Add(_sendCustom);
            Button clear = new Button { Text = "清空日志", Location = new Point(825, 8), Size = new Size(85, 29) };
            clear.Click += delegate { _log.Clear(); };
            command.Controls.Add(clear);
            page.Controls.Add(command);

            _log.Dock = DockStyle.Fill;
            _log.Multiline = true;
            _log.ScrollBars = ScrollBars.Both;
            _log.WordWrap = false;
            _log.ReadOnly = true;
            _log.BackColor = Color.FromArgb(25, 25, 25);
            _log.ForeColor = Color.Gainsboro;
            _log.Font = new Font("Consolas", 9F);
            page.Controls.Add(_log);
            command.BringToFront();
            return page;
        }

        private void RefreshPorts()
        {
            string selected = _ports.SelectedItem as string;
            string[] names = SerialPort.GetPortNames();
            Array.Sort(names);
            _ports.Items.Clear();
            _ports.Items.AddRange(names);
            if (selected != null && _ports.Items.Contains(selected)) _ports.SelectedItem = selected;
            else if (_ports.Items.Count > 0) _ports.SelectedIndex = 0;
        }

        private void ConnectClicked(object sender, EventArgs e)
        {
            try
            {
                if (_serial.IsOpen)
                {
                    TryRestoreRelayHigh();
                    _serial.Close();
                    SetConnected(false);
                    return;
                }
                if (_ports.SelectedItem == null) throw new InvalidOperationException("未发现可用串口");
                _serial.Open(_ports.SelectedItem.ToString(), int.Parse(_baud.SelectedItem.ToString(), CultureInfo.InvariantCulture));
                SetConnected(true);
                AppendLog("[工具] 已连接 " + _serial.PortName + "\r\n");
            }
            catch (Exception ex) { MessageBox.Show(ex.Message, "连接失败", MessageBoxButtons.OK, MessageBoxIcon.Error); }
        }

        private void SetConnected(bool connected)
        {
            _connect.Text = connected ? "断开设备" : "连接设备";
            _connectionState.Text = connected ? "● 已连接" : "● 未连接";
            _connectionState.ForeColor = connected ? Color.SeaGreen : Color.Firebrick;
        }

        private void SerialDataReceived(string data)
        {
            ParseLiveData(data);
            if (!IsHandleCreated) return;
            BeginInvoke((MethodInvoker)delegate { AppendLog(data); });
        }

        private void ParseLiveData(string data)
        {
            Match m = Regex.Match(data, @"vcar\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*V", RegexOptions.IgnoreCase);
            if (m.Success) double.TryParse(m.Groups[1].Value, NumberStyles.Float, CultureInfo.InvariantCulture, out _latestCarVoltage);
            if (data.IndexOf("[ALARM] SOS active", StringComparison.OrdinalIgnoreCase) >= 0) SetTestThreadSafe(11, "SOS active", "通过", "检测到 SOS 持续触发日志");
        }

        private void AppendLog(string text)
        {
            if (_log.TextLength > 300000) _log.Clear();
            _log.AppendText(text);
            _log.SelectionStart = _log.TextLength;
            _log.ScrollToCaret();
        }

        private void RunWorker(Action action)
        {
            if (_busy) { MessageBox.Show("当前任务尚未完成。", "A300"); return; }
            if (!_serial.IsOpen) { MessageBox.Show("请先连接 A300 串口。", "A300"); return; }
            SaveUiSettings();
            _busy = true;
            Task.Factory.StartNew(delegate
            {
                try { action(); }
                catch (Exception ex)
                {
                    MarkActiveRecordError(ex.Message);
                    Ui(delegate { MessageBox.Show(ex.Message, "执行失败", MessageBoxButtons.OK, MessageBoxIcon.Error); });
                }
                finally
                {
                    if (_relayTestMayBeLow) TryRestoreRelayHigh();
                    _busy = false;
                }
            });
        }

        private void MarkActiveRecordError(string message)
        {
            lock (_recordLock)
            {
                if (_activeSummaryPath.Length == 0) return;
                _recordWriteSummary = "执行异常：" + message;
            }
            PersistRealtimeRecord();
        }

        private string Command(string command, int timeoutMs)
        {
            Ui(delegate { AppendLog("\r\n[TX] " + command + "\r\n"); });
            string response = _serial.SendCommand(command, timeoutMs);
            if (response.Length == 0) Ui(delegate { AppendLog("[工具] 等待响应超时\r\n"); });
            return response;
        }

        private string CommandBytes(string commandKey, byte[] wireBytes, int timeoutMs)
        {
            Ui(delegate { AppendLog("\r\n[TX] " + commandKey + ",<GBK>\r\n"); });
            string response = _serial.SendCommandBytes(commandKey, wireBytes, timeoutMs);
            if (response.Length == 0) Ui(delegate { AppendLog("[工具] 等待响应超时\r\n"); });
            return response;
        }

        private string FactoryQuery(string command, int timeoutMs)
        {
            string response = "";
            for (int attempt = 0; attempt < 2; attempt++)
            {
                response = Command(command, timeoutMs);
                if (response.Length > 0) return response;
            }
            return response;
        }

        private static string FailureClassText(FailureClass value)
        {
            switch (value)
            {
                case FailureClass.CommunicationTimeout: return "通信超时";
                case FailureClass.UnsupportedByFirmware: return "固件不支持";
                case FailureClass.FirmwareDriverFailure: return "固件/驱动失败";
                case FailureClass.MeasurementOutOfRange: return "测量值超限";
                case FailureClass.PendingOperatorConfirmation: return "待操作员确认";
                case FailureClass.HardwareFailure: return "硬件失败";
                case FailureClass.SkippedNotTested: return "跳过/未测试";
                default: return "";
            }
        }

        private void SetFactoryTest(int number, string detected, string result,
                                    string note, string rawResponse,
                                    FailureClass failureClass,
                                    string operatorConfirmation)
        {
            TestItem item = _tests[number];
            lock (_recordLock)
            {
                item.RawResponse = rawResponse ?? "";
                item.FailureReason = FailureClassText(failureClass);
                item.OperatorConfirmation = operatorConfirmation ?? "";
            }
            SetTest(number, detected, result, note);
        }

        private bool LoadFactoryCapabilities()
        {
            string response = FactoryQuery("FACTORYCAP#", 1800);
            _latestCapabilityResponse = response;
            FactoryCapabilities capabilities;
            if (!FactoryCapabilities.TryParse(response, out capabilities) || capabilities.Version != 1)
            {
                _factoryCapabilities = null;
                _factoryCapabilityVersion = "";
                return false;
            }
            _factoryCapabilities = capabilities;
            _factoryCapabilityVersion = capabilities.Version.ToString(CultureInfo.InvariantCulture);
            return true;
        }

        private bool CapabilitySupported(int testNumber)
        {
            if (_factoryCapabilities == null) return false;
            switch (testNumber)
            {
                case 7: return _factoryCapabilities.Acc;
                case 8: return _factoryCapabilities.Gsensor;
                case 9: return _factoryCapabilities.Voltage;
                case 10: return _factoryCapabilities.Relay;
                case 12: return _factoryCapabilities.Tts;
                default: return true;
            }
        }

        private void SetUnsupportedFactoryTest(int number, string capabilityResponse)
        {
            SetFactoryTest(number, capabilityResponse.Length == 0 ? "无 FACTORYCAP 响应" : capabilityResponse,
                "不通过", "当前固件未声明该生产测试能力", capabilityResponse,
                FailureClass.UnsupportedByFirmware, "");
        }

        private static bool RelayIsHigh(string response)
        {
            FactoryRelay relay;
            return FactoryMeasurements.TryParseRelay(response, out relay) &&
                   !relay.ExternalLow && !relay.McuAsserted && !relay.PadAsserted;
        }

        private bool TryRestoreRelayHigh()
        {
            if (!_serial.IsOpen) return false;
            try
            {
                string status = _serial.SendCommand("RELAYTEST,STATUS#", 700);
                if (!RelayIsHigh(status))
                {
                    string restored = _serial.SendCommand("RELAYTEST,HIGH#", 900);
                    if (!RelayIsHigh(restored)) return false;
                    status = _serial.SendCommand("RELAYTEST,STATUS#", 700);
                    if (!RelayIsHigh(status)) return false;
                }
                _relayTestMayBeLow = false;
                return true;
            }
            catch { return false; }
        }

        private bool EnsureFactoryReadyForUnit()
        {
            if (!LoadFactoryCapabilities()) return false;
            return !_factoryCapabilities.Relay || TryRestoreRelayHigh();
        }

        private void ReadParameters()
        {
            string response = Command("PARAM#", 3500);
            _latestParam = response;
            Dictionary<string, string> p = ParseParam(response);
            if (p.Count == 0) throw new InvalidOperationException("未收到有效 PARAM 响应，请检查串口和固件版本。\r\n收到：" + response);
            _latestImei = Get(p, "IMEI");
            Ui(delegate
            {
                _fields["identity"].Text = _syncImeiTerminal.Checked && Regex.IsMatch(_latestImei, @"^\d{15}$") ? _latestImei : Get(p, "PID");
                if (Get(p, "MODEL").Length > 0) _fields["terminal_model"].Text = Get(p, "MODEL");
                SetHostPortFields(Get(p, "IP"), "main_ip", "main_port");
                SetHostPortFields(Get(p, "FIP"), "backup_ip", "backup_port");
                string force = Get(p, "FORCE");
                string[] f = force.Split(':');
                if (f.Length == 2) { _fields["acc_on_interval"].Text = f[0]; _fields["acc_off_interval"].Text = f[1]; }
            });
            string apn = Command("APN#", 2200);
            Match am = Regex.Match(apn, @"APN,([^,\r\n]*),([^,\r\n]*),([^=\r\n]*)=Success", RegexOptions.IgnoreCase);
            if (am.Success) Ui(delegate { _fields["apn"].Text = am.Groups[1].Value; _fields["apn_user"].Text = am.Groups[2].Value; _fields["apn_pass"].Text = am.Groups[3].Value; });
            string rtk = Command("RTKINFO#", 1800);
            Match rm = Regex.Match(rtk, @"RTKINFO,([^,]*),(\d+),([^,]*),([^,]*),([^=\r\n]*)=Success", RegexOptions.IgnoreCase);
            if (rm.Success) Ui(delegate { _fields["rtk_ip"].Text = rm.Groups[1].Value; _fields["rtk_port"].Text = rm.Groups[2].Value; _fields["rtk_mount"].Text = rm.Groups[3].Value; _fields["rtk_user"].Text = rm.Groups[4].Value; _fields["rtk_pass"].Text = rm.Groups[5].Value; });
            Ui(delegate { MessageBox.Show("设备参数读取完成。", "A300"); });
        }

        private void WriteAllParameters()
        {
            string message;
            WriteAllParametersCore(true, out message);
        }

        private bool WriteAllParametersCore(bool showDialog, out string message)
        {
            Dictionary<string, string> v = SnapshotFields();
            ValidateParameters(v);
            List<string> failures = new List<string>();
            bool writeMain = v["main_ip"].Length > 0 || v["main_port"].Length > 0;
            bool writeBackup = v["backup_ip"].Length > 0 || v["backup_port"].Length > 0;
            bool writeIdentity = v["identity"].Length > 0;
            bool writeModel = v["terminal_model"].Length > 0;
            bool writeApn = v["apn"].Length > 0 || v["apn_user"].Length > 0 || v["apn_pass"].Length > 0;
            bool writeIntervals = v["acc_on_interval"].Length > 0 || v["acc_off_interval"].Length > 0;
            bool writeRtk = RtkWriteEnabled();
            BeginWriteRecord(v, writeMain, writeBackup, writeIdentity, writeModel, writeApn, writeIntervals, writeRtk);
            if (v["imei_input"].Length == 15)
            {
                Dictionary<string, string> before = ParseParam(Command("PARAM#", 3500));
                if (Get(before, "IMEI") != v["imei_input"])
                {
                    failures.Add("IMEI与设备模组读取值不一致（本工具不改写模组IMEI）");
                    SetWriteResult("IMEI校验", "不一致：设备=" + Get(before, "IMEI"));
                }
                else SetWriteResult("IMEI校验", "一致");
            }
            if (writeMain) WriteAndCheck("主平台", "IP," + v["main_ip"] + "," + v["main_port"] + "#", failures);
            if (writeBackup) WriteAndCheck("副平台", "FIP," + v["backup_ip"] + "," + v["backup_port"] + "#", failures);
            if (writeIdentity) WriteAndCheck("终端ID", "PID," + v["terminal_id"] + "#", failures);
            if (writeModel) WriteAndCheck("终端型号", "MODEL," + v["terminal_model"] + "#", failures);
            if (writeApn) WriteAndCheck("APN", "APN," + v["apn"] + "," + v["apn_user"] + "," + v["apn_pass"] + "#", failures);
            if (writeIntervals) WriteAndCheck("上报间隔", "FREQ," + v["acc_on_interval"] + "," + v["acc_off_interval"] + "#", failures);
            bool rtkWriteOk = !writeRtk;
            if (writeRtk)
            {
                int failureCount = failures.Count;
                WriteAndCheck("RTK", "RTKINFO," + v["rtk_ip"] + "," + v["rtk_port"] + "," + v["rtk_mount"] + "," + v["rtk_user"] + "," + v["rtk_pass"] + "#", failures);
                rtkWriteOk = failures.Count == failureCount;
            }

            string verify = Command("PARAM#", 3500);
            _latestParam = verify;
            Dictionary<string, string> p = ParseParam(verify);
            if (Get(p, "IMEI").Length > 0) _latestImei = Get(p, "IMEI");
            bool coreOk = p.Count > 0;
            if (writeIdentity) coreOk = coreOk && Get(p, "PID") == v["terminal_id"];
            if (writeModel) coreOk = coreOk && Get(p, "MODEL") == v["terminal_model"];
            if (writeMain) coreOk = coreOk && Get(p, "IP") == v["main_ip"] + ":" + v["main_port"];
            if (writeBackup) coreOk = coreOk && Get(p, "FIP") == v["backup_ip"] + ":" + v["backup_port"];
            if (writeIntervals) coreOk = coreOk && Get(p, "FORCE") == v["acc_on_interval"] + ":" + v["acc_off_interval"];
             
            if (!coreOk) failures.Add("PARAM 复检不一致");
            if (writeIdentity) AppendWriteResult("终端ID", p.Count == 0 ? "复检无响应" : (Get(p, "PID") == v["terminal_id"] ? "复检通过" : "复检不一致：设备=" + Get(p, "PID")));
            if (writeModel) AppendWriteResult("终端型号", p.Count == 0 ? "复检无响应" : (Get(p, "MODEL") == v["terminal_model"] ? "复检通过" : "复检不一致：设备=" + Get(p, "MODEL")));
            if (writeMain) AppendWriteResult("主平台", p.Count == 0 ? "复检无响应" : (Get(p, "IP") == v["main_ip"] + ":" + v["main_port"] ? "复检通过" : "复检不一致：设备=" + Get(p, "IP")));
            if (writeBackup) AppendWriteResult("副平台", p.Count == 0 ? "复检无响应" : (Get(p, "FIP") == v["backup_ip"] + ":" + v["backup_port"] ? "复检通过" : "复检不一致：设备=" + Get(p, "FIP")));
            if (writeIntervals) AppendWriteResult("上报间隔", p.Count == 0 ? "复检无响应" : (Get(p, "FORCE") == v["acc_on_interval"] + ":" + v["acc_off_interval"] ? "复检通过" : "复检不一致：设备=" + Get(p, "FORCE")));

            if (writeApn)
            {
                string apnVerify = Command("APN#", 2200);
                string expectedApn = "APN," + v["apn"] + "," + v["apn_user"] + "," + v["apn_pass"] + "=Success";
                if (apnVerify.IndexOf(expectedApn, StringComparison.OrdinalIgnoreCase) < 0)
                {
                    failures.Add("APN 复检不一致");
                    AppendWriteResult("APN", "复检不一致：" + LastLine(apnVerify));
                }
                else AppendWriteResult("APN", "复检通过");
            }
            if (writeRtk)
            {
                string rtkVerify = Command("RTKINFO#", 2200);
                string expectedRtk = "RTKINFO," + v["rtk_ip"] + "," + v["rtk_port"] + "," + v["rtk_mount"] + "," + v["rtk_user"] + "," + v["rtk_pass"] + "=Success";
                if (rtkVerify.IndexOf(expectedRtk, StringComparison.OrdinalIgnoreCase) < 0)
                {
                    failures.Add("RTK 复检不一致");
                    rtkWriteOk = false;
                    AppendWriteResult("RTK", "复检不一致：" + LastLine(rtkVerify));
                }
                else AppendWriteResult("RTK", "复检通过");
            }

            if (writeRtk && rtkWriteOk && _rtkExcelPath.Length > 0) CommitPendingRtkAccount();

            message = failures.Count == 0 ? "全部参数写入并复检成功。" : "写入完成，但以下项目失败：\r\n- " + string.Join("\r\n- ", failures.ToArray());
            CompleteWriteRecord(failures.Count == 0, failures);
            if (showDialog)
            {
                string dialogMessage = message;
                Ui(delegate { MessageBox.Show(dialogMessage, failures.Count == 0 ? "写入成功" : "写入有失败", MessageBoxButtons.OK, failures.Count == 0 ? MessageBoxIcon.Information : MessageBoxIcon.Warning); });
            }
            return failures.Count == 0;
        }

        private void WriteParametersAndRunTests()
        {
            SetWorkflowState("正在确认生产测试接口和断油输出安全状态...", Color.FromArgb(30, 105, 180));
            if (!EnsureFactoryReadyForUnit())
            {
                SetWorkflowState("固件不兼容或无法确认断油输出 HIGH，禁止开始下一台", Color.Firebrick);
                Ui(delegate { MessageBox.Show("需要 V1.281 FACTORYCAP,VER=1，且断油输出必须确认 HIGH。", "生产测试已阻止", MessageBoxButtons.OK, MessageBoxIcon.Error); });
                FocusScannerForNextUnit(false);
                return;
            }
            SetWorkflowState("正在写入全部参数...", Color.FromArgb(30, 105, 180));
            string message;
            bool writeOk = WriteAllParametersCore(false, out message);
            if (!writeOk)
            {
                SetWorkflowState("参数写入失败，已停止测试", Color.Firebrick);
                string failure = message;
                Ui(delegate { MessageBox.Show(failure, "自动流程停止", MessageBoxButtons.OK, MessageBoxIcon.Warning); });
                FocusScannerForNextUnit(false);
                return;
            }

            SetWorkflowState("参数写入成功，正在自动测试...", Color.SeaGreen);
            Ui(delegate { _tabs.SelectedIndex = 0; });
            RunAllTests();
            SetWorkflowState("自动测试完成，请处理待人工项目", Color.SeaGreen);
            FocusScannerForNextUnit(true);
        }

        private void FocusScannerForNextUnit(bool clear)
        {
            Ui(delegate
            {
                if (clear) _fields["identity"].Clear();
                else _fields["identity"].SelectAll();
                _fields["identity"].Focus();
            });
        }

        private void WriteAndCheck(string name, string command, List<string> failures)
        {
            string response = Command(command, 2500);
            if (!IsSuccess(response))
            {
                string detail = response.Length == 0 ? "超时" : LastLine(response);
                failures.Add(name + "：" + detail);
                SetWriteResult(name, "写入失败：" + detail);
            }
            else SetWriteResult(name, "写入响应成功");
        }

        private void BeginWriteRecord(Dictionary<string, string> values, bool writeMain, bool writeBackup, bool writeIdentity, bool writeModel, bool writeApn, bool writeIntervals, bool writeRtk)
        {
            _latestParam = "";
            _latestImei = "";
            _latestCarVoltage = -1;
            lock (_recordLock)
            {
                _recordStartedAt = DateTime.Now;
                _recordTerminalId = values["terminal_id"];
                _recordImeiInput = values["imei_input"];
                _recordWriteSummary = "参数写入中";
                _recordParameters.Clear();
                foreach (KeyValuePair<string, string> pair in values) _recordParameters[pair.Key] = pair.Value;
                _recordWriteResults.Clear();
                _recordWriteResults["IMEI校验"] = values["imei_input"].Length == 15 ? "待校验" : "未校验（未勾选IMEI同步）";
                _recordWriteResults["主平台"] = writeMain ? "待写入" : "跳过（参数为空）";
                _recordWriteResults["副平台"] = writeBackup ? "待写入" : "跳过（参数为空）";
                _recordWriteResults["终端ID"] = writeIdentity ? "待写入" : "跳过（参数为空）";
                _recordWriteResults["终端型号"] = writeModel ? "待写入" : "跳过（参数为空）";
                _recordWriteResults["APN"] = writeApn ? "待写入" : "跳过（参数为空）";
                _recordWriteResults["上报间隔"] = writeIntervals ? "待写入" : "跳过（参数为空）";
                _recordWriteResults["RTK"] = writeRtk ? "待写入" : "跳过（未勾选）";
            }
            PrepareActiveRecord(values);
            for (int i = 1; i <= 14; i++) SetTest(i, "", "等待", _tests[i].Note);
            UpdateSummary();
            PersistRealtimeRecord();
        }

        private void SetWriteResult(string name, string result)
        {
            lock (_recordLock) _recordWriteResults[name] = result;
            PersistRealtimeRecord();
        }

        private void AppendWriteResult(string name, string result)
        {
            lock (_recordLock)
            {
                string current;
                _recordWriteResults.TryGetValue(name, out current);
                _recordWriteResults[name] = string.IsNullOrEmpty(current) ? result : current + "；" + result;
            }
            PersistRealtimeRecord();
        }

        private void CompleteWriteRecord(bool success, List<string> failures)
        {
            lock (_recordLock)
            {
                _recordWriteSummary = success ? "全部参数写入并复检成功" : "参数写入失败：" + string.Join("；", failures.ToArray());
            }
            PersistRealtimeRecord();
        }

        private void ValidateParameters(Dictionary<string, string> v)
        {
            if (!_orderReady || !ValidOrderNumber(v["order_no"])) throw new InvalidOperationException("请先使用顶部“新建”或“加载”按钮选择订单。 ");
            bool mainAny = v["main_ip"].Length > 0 || v["main_port"].Length > 0;
            if (mainAny && (v["main_ip"].Length == 0 || !ValidPort(v["main_port"]))) throw new InvalidOperationException("主平台IP和端口必须同时填写，端口范围1-65535。 ");
            bool backupAny = v["backup_ip"].Length > 0 || v["backup_port"].Length > 0;
            if (backupAny && (v["backup_ip"].Length == 0 || !ValidPort(v["backup_port"]))) throw new InvalidOperationException("副平台IP和端口必须同时填写，整组空白则跳过。 ");
            if (v["identity"].Length > 0)
            {
                bool syncImei = SyncImeiTerminalEnabled();
                if (syncImei && !Regex.IsMatch(v["identity"], @"^\d{15}$")) throw new InvalidOperationException("勾选IMEI同步时必须填写15位IMEI。 ");
                if (!syncImei && !Regex.IsMatch(v["identity"], @"^\d{11}$")) throw new InvalidOperationException("未勾选IMEI同步时必须填写自定义11位终端ID。 ");
            }
            if (v["terminal_model"].Length > 0 && !ValidTerminalModel(v["terminal_model"]))
                throw new InvalidOperationException("终端型号必须为1-20位可打印ASCII字符，不能包含空格、英文逗号或#号。 ");
            bool apnAny = v["apn"].Length > 0 || v["apn_user"].Length > 0 || v["apn_pass"].Length > 0;
            if (apnAny && v["apn"].Length == 0) throw new InvalidOperationException("填写APN用户名或密码时必须同时填写APN。 ");
            int on, off;
            bool intervalAny = v["acc_on_interval"].Length > 0 || v["acc_off_interval"].Length > 0;
            if (intervalAny && (!int.TryParse(v["acc_on_interval"], out on) || on < 1 || on > 300 || !int.TryParse(v["acc_off_interval"], out off) || off < 5 || off > 65535)) throw new InvalidOperationException("ACC ON和ACC OFF间隔必须同时填写；ACC ON范围1-300秒，ACC OFF范围5-65535秒。 ");
            if (RtkWriteEnabled())
            {
                if (v["rtk_ip"].Length == 0 || !ValidPort(v["rtk_port"]) || v["rtk_user"].Length == 0 || v["rtk_pass"].Length == 0 || v["rtk_mount"].Length == 0) throw new InvalidOperationException("已勾选RTK写入，RTK服务、端口、账号、密码和挂载点必须完整填写。 ");
                if (InvalidRtkValue(v["rtk_ip"]) || InvalidRtkValue(v["rtk_user"]) || InvalidRtkValue(v["rtk_pass"]) || InvalidRtkValue(v["rtk_mount"])) throw new InvalidOperationException("RTK参数不能包含英文逗号、#号或换行。 ");
                if (_rtkExcelPath.Length > 0)
                {
                    if (_pendingRtkAccount == null) throw new InvalidOperationException("请先扫码，由工具按Excel顺序分配下一条RTK账号。 ");
                    if (!PendingRtkMatches(v)) throw new InvalidOperationException("当前RTK参数与Excel顺序分配记录不一致，请重新扫码恢复。 ");
                }
            }
        }

        private bool PendingRtkMatches(Dictionary<string, string> values)
        {
            return _pendingRtkAccount != null && values["rtk_ip"] == _pendingRtkAccount.Host && values["rtk_port"] == _pendingRtkAccount.Port && values["rtk_user"] == _pendingRtkAccount.User && values["rtk_pass"] == _pendingRtkAccount.Password && values["rtk_mount"] == _pendingRtkAccount.Mount;
        }

        private static bool InvalidRtkValue(string value)
        {
            return value.IndexOf(',') >= 0 || value.IndexOf('#') >= 0 || value.IndexOf('\r') >= 0 || value.IndexOf('\n') >= 0;
        }

        private static bool ValidTerminalModel(string value)
        {
            if (string.IsNullOrEmpty(value) || value.Length > 20) return false;
            foreach (char c in value) if (c < 0x21 || c > 0x7E || c == ',' || c == '#') return false;
            return true;
        }

        private static bool ValidPort(string text)
        {
            int port;
            return int.TryParse(text, out port) && port >= 1 && port <= 65535;
        }

        private void RunAllTests()
        {
            EnsureActiveRecordForCurrentFields();
            SyncTestPresetsFromParameters();
            for (int i = 1; i <= 14; i++)
            {
                lock (_recordLock)
                {
                    _tests[i].RawResponse = "";
                    _tests[i].FailureReason = "";
                    _tests[i].OperatorConfirmation = "";
                }
                SetTest(i, "", (i == 14 || !TestEnabled(i)) ? "跳过" : "检测中", _tests[i].Note);
            }
            string param = Command("PARAM#", 3500);
            _latestParam = param;
            Dictionary<string, string> p = ParseParam(param);
            if (p.Count == 0)
            {
                for (int i = 1; i <= 14; i++)
                    if (TestEnabled(i)) SetTest(i, "无有效 PARAM 响应", "不通过", "请检查串口接线、波特率和 A300 固件");
                return;
            }
            _latestImei = Get(p, "IMEI");
            bool factoryReady = LoadFactoryCapabilities();
            if (factoryReady && _factoryCapabilities.Relay && !TryRestoreRelayHigh())
            {
                for (int i = 7; i <= 12; i++)
                    if (i != 11 && TestEnabled(i)) SetFactoryTest(i, "无法确认 RELAY HIGH", "不通过", "安全前置条件失败，硬件测试未执行", _latestCapabilityResponse, FailureClass.FirmwareDriverFailure, "");
                SetFactoryTest(14, "V1.281: RS485=0", "跳过", "本版本未纳入 RS485 生产测试", _latestCapabilityResponse, FailureClass.SkippedNotTested, "");
                UpdateSummary();
                return;
            }
            if (TestEnabled(1)) TestVersion(p);
            if (TestEnabled(2)) TestServers(p);
            if (TestEnabled(3)) TestTerminalId(p);
            if (TestEnabled(4)) TestSim(p);
            if (TestEnabled(5)) TestCsq(p);
            if (TestEnabled(6)) TestGps(p);
            if (TestEnabled(7)) { if (factoryReady && CapabilitySupported(7)) TestAcc(p); else SetUnsupportedFactoryTest(7, _latestCapabilityResponse); }
            if (TestEnabled(8)) { if (factoryReady && CapabilitySupported(8)) TestGsensor(); else SetUnsupportedFactoryTest(8, _latestCapabilityResponse); }
            if (TestEnabled(9)) { if (factoryReady && CapabilitySupported(9)) TestVoltage(); else SetUnsupportedFactoryTest(9, _latestCapabilityResponse); }
            if (TestEnabled(10)) { if (factoryReady && CapabilitySupported(10)) TestRelay(); else SetUnsupportedFactoryTest(10, _latestCapabilityResponse); }
            if (TestEnabled(11)) SetTest(11, "等待 SOS 触发", "待人工", "SOS 线接地保持 " + TestValue(11) + " 秒；检测到日志后自动通过");
            if (TestEnabled(12)) { if (factoryReady && CapabilitySupported(12)) TestTts(); else SetUnsupportedFactoryTest(12, _latestCapabilityResponse); }
            if (TestEnabled(13)) SetTest(13, "PARAM 双向收发成功", "通过", "调试 UART TX、RX 正常");
            SetFactoryTest(14, "V1.281: RS485=0", "跳过", "本版本未纳入 RS485 生产测试", _latestCapabilityResponse, FailureClass.SkippedNotTested, "");
            UpdateSummary();
        }

        private void TestVersion(Dictionary<string, string> p)
        {
            string actual = Get(p, "VER");
            string expected = TestValue(1);
            string semantic;
            bool parsed = SemanticFirmwareVersion.TryExtract(actual, out semantic);
            bool ok = parsed && (expected.Length == 0 || string.Equals(semantic, expected, StringComparison.OrdinalIgnoreCase));
            _firmwareFullVersion = actual;
            _firmwareSemanticVersion = parsed ? semantic : "";
            SetTest(1, actual, ok ? "通过" : "不通过", expected.Length == 0 ? "已读取固件语义版本=" + semantic : "预设语义版本=" + expected + "；构建时间不参与匹配");
        }

        private void TestServers(Dictionary<string, string> p)
        {
            string expectedMain = TestValue(2);
            string actualMain = Get(p, "IP");
            string actualBackup = Get(p, "FIP");
            bool mainConfigured = expectedMain.Length > 0;
            bool ok = !mainConfigured || actualMain == expectedMain;
            SetTest(2, "主=" + actualMain + "；副=" + actualBackup, ok ? "通过" : "不通过", mainConfigured ? "预设主=" + expectedMain : "未预设，仅显示设备读取值");
        }

        private void TestTerminalId(Dictionary<string, string> p)
        {
            string id = Get(p, "PID");
            string expected = TestValue(3);
            bool ok = Regex.IsMatch(id, @"^\d{11}$") && (expected.Length == 0 || id == expected);
            string imeiId = _latestImei.Length >= 11 ? _latestImei.Substring(_latestImei.Length - 11) : "";
            bool syncImei = SyncImeiTerminalEnabled();
            bool passed = ok && (!syncImei || imeiId.Length == 0 || id == imeiId);
            SetTest(3, "PID=" + id + "；IMEI后11位=" + imeiId, passed ? "通过" : "不通过", syncImei ? "已勾选同步：终端ID须等于IMEI后11位" : "自定义模式：终端ID只需与扫码写入值一致");
        }

        private void TestSim(Dictionary<string, string> p)
        {
            string iccid = Get(p, "ICCID").Trim();
            bool ok = iccid.Length > 0;
            SetTest(4, ok ? iccid : "未检测到 ICCID", ok ? "通过" : "不通过", ok ? "已读取到流量卡 ICCID 信息" : "检查 SIM 卡方向、卡槽与模组通信");
        }

        private void TestCsq(Dictionary<string, string> p)
        {
            int actual, min;
            int.TryParse(Get(p, "CSQ"), out actual);
            int.TryParse(TestValue(5), out min);
            bool ok = min >= 10 && min <= 33 && actual >= min && actual <= 33;
            SetTest(5, "CSQ=" + actual, ok ? "通过" : "不通过", "达标值=" + min + "（允许配置 10-33）");
        }

        private void TestGps(Dictionary<string, string> p)
        {
            int minSats, minCn, stableRequired;
            double maxHdop;
            ParseGpsThreshold(TestValue(6), out minSats, out minCn, out maxHdop, out stableRequired);
            DateTime deadline = DateTime.UtcNow.AddMilliseconds(TestTimeoutMs(6));
            int stable = 0;
            bool metricsAvailable = false;
            string detected = "等待GPS质量数据";
            string failureReason = "尚未获得有效定位";
            SetTest(6, detected, "检测中", "需连续" + stableRequired + "次达到：天线正常、FIX>0，卫星≥" + minSats + "，平均CN≥" + minCn + "，最大CN≥" + (minCn + 5) + "，HDOP≤" + maxHdop.ToString("0.0", CultureInfo.InvariantCulture));

            while (true)
            {
                string ant = Get(p, "ANT");
                if (ant.Length > 0 && ant != "OK" && ant != "UNKNOWN")
                {
                    string antStatus = (ant == "OPEN") ? "天线开路（未接或接触不良）" :
                                       (ant == "SHORT") ? "天线短路" : "天线异常：" + ant;
                    SetTest(6, "ANT[" + ant + "]；GNSS天线故障", "不通过", antStatus + "。必须接上有效的GPS/GNSS天线才能通过测试");
                    return;
                }
                int fix = 0, sats = 0, cnSats = 0, cnAvg = 0, cnMax = 0;
                double hdop = 0.0;
                metricsAvailable = int.TryParse(Get(p, "FIX"), out fix) &&
                    int.TryParse(Get(p, "GPS"), out sats) &&
                    double.TryParse(Get(p, "HDOP"), NumberStyles.Float, CultureInfo.InvariantCulture, out hdop) &&
                    int.TryParse(Get(p, "CNSAT"), out cnSats) &&
                    int.TryParse(Get(p, "CNAVG"), out cnAvg) &&
                    int.TryParse(Get(p, "CNMAX"), out cnMax);
                if (metricsAvailable)
                {
                    bool fixOk = fix > 0;
                    bool satsOk = sats >= minSats && cnSats >= minSats;
                    bool cnOk = cnAvg >= minCn && cnMax >= minCn + 5;
                    bool hdopOk = hdop > 0.0 && hdop <= maxHdop;
                    detected = "ANT[" + (ant.Length > 0 ? ant : "?") + "]；FIX=" + fix + "；有效/有CN卫星=" + sats + "/" + cnSats + "；CN平均/最大=" + cnAvg + "/" + cnMax + "；HDOP=" + hdop.ToString("0.0", CultureInfo.InvariantCulture) + "；连续=" + stable + "/" + stableRequired;
                    if (fixOk && satsOk && cnOk && hdopOk)
                    {
                        stable++;
                        detected = "ANT[" + (ant.Length > 0 ? ant : "?") + "]；FIX=" + fix + "；有效/有CN卫星=" + sats + "/" + cnSats + "；CN平均/最大=" + cnAvg + "/" + cnMax + "；HDOP=" + hdop.ToString("0.0", CultureInfo.InvariantCulture) + "；连续=" + stable + "/" + stableRequired;
                        if (stable >= stableRequired)
                        {
                            SetTest(6, detected, "通过", "天线状态正常、定位状态、卫星数、C/N0和HDOP连续稳定达标");
                            return;
                        }
                    }
                    else
                    {
                        stable = 0;
                        if (!fixOk) failureReason = "未获得有效定位";
                        else if (!satsOk) failureReason = "有效卫星或有CN卫星数不足";
                        else if (!cnOk) failureReason = "平均/最大C/N0不足，疑似天线接错、接触不良或灵敏度不足";
                        else failureReason = "HDOP过大，定位几何质量不合格";
                    }
                }
                else failureReason = "固件未输出FIX/HDOP/CNSAT/CNAVG/CNMAX，严谨模式禁止仅按卫星数通过";

                int remaining = (int)(deadline - DateTime.UtcNow).TotalMilliseconds;
                if (remaining <= 0)
                {
                    SetTest(6, detected, "不通过", failureReason);
                    return;
                }

                SetTest(6, detected, "检测中", failureReason + "；需连续达标 " + stableRequired + " 次");
                Thread.Sleep(Math.Min(1100, remaining));
                remaining = (int)(deadline - DateTime.UtcNow).TotalMilliseconds;
                if (remaining <= 0) continue;
                p = ParseParam(Command("PARAM#", Math.Min(1800, remaining)));
            }
        }

        private void TestAcc(Dictionary<string, string> p)
        {
            AccTransitionTracker tracker = new AccTransitionTracker(2);
            DateTime deadline = DateTime.UtcNow.AddMilliseconds(TestTimeoutMs(7));
            string lastResponse = "";
            string detected = "等待 ACCSTAT";
            int validSamples = 0;
            SetTest(7, detected, "检测中", "请将 ACC 有电、断电各切换两次；判定使用 DEB，RAW/HW/LOGIC 仅诊断");

            while (DateTime.UtcNow < deadline)
            {
                int remaining = (int)(deadline - DateTime.UtcNow).TotalMilliseconds;
                if (remaining <= 0) break;
                lastResponse = FactoryQuery("ACCSTAT#", Math.Min(900, remaining));
                if (lastResponse.Length == 0) continue;
                ProductionReply reply;
                if (ProductionReply.TryParse(lastResponse, "ACCSTAT", out reply) && !reply.Success)
                {
                    SetFactoryTest(7, lastResponse, "不通过", "ACC 快照读取失败：" + reply.ErrorCode,
                        lastResponse, FailureClass.FirmwareDriverFailure, "");
                    return;
                }
                FactoryAcc acc;
                if (!FactoryMeasurements.TryParseAcc(lastResponse, out acc))
                {
                    SetFactoryTest(7, lastResponse, "不通过", "ACCSTAT 响应格式无效",
                        lastResponse, FailureClass.FirmwareDriverFailure, "");
                    return;
                }
                validSamples++;
                detected = "RAW=" + (acc.Raw ? "1" : "0") + "；DEB=" + (acc.Debounced ? "1" : "0") +
                    "；HW=" + (acc.HardwarePriority ? "1" : "0") + "；LOGIC=" + (acc.LogicalOn ? "1" : "0") +
                    "；有电=" + tracker.OnCount + "/2；断电=" + tracker.OffCount + "/2";
                bool complete = tracker.Add(acc.Debounced);
                detected = "RAW=" + (acc.Raw ? "1" : "0") + "；DEB=" + (acc.Debounced ? "1" : "0") +
                    "；HW=" + (acc.HardwarePriority ? "1" : "0") + "；LOGIC=" + (acc.LogicalOn ? "1" : "0") +
                    "；有电=" + tracker.OnCount + "/2；断电=" + tracker.OffCount + "/2";
                if (complete)
                {
                    SetFactoryTest(7, detected, "通过", "DEB 已检测到两次 ON 和两次 OFF 转换",
                        lastResponse, FailureClass.None, "");
                    return;
                }
                SetTest(7, detected, "检测中", "继续切换 ACC，重复相同状态不计数");
                Thread.Sleep(Math.Min(250, Math.Max(1, remaining)));
            }
            FailureClass failure = validSamples == 0 ? FailureClass.CommunicationTimeout : FailureClass.MeasurementOutOfRange;
            SetFactoryTest(7, detected, "不通过", validSamples == 0 ? "ACCSTAT 两次尝试均无关联响应" : "超时：未完成两次 ON/OFF 转换",
                lastResponse, failure, "");
        }

        private static string NormalizeAccState(string value)
        {
            string state = (value ?? "").Trim();
            if (state == "0" || state == "1") return state;
            Match match = Regex.Match(state, @"(?:^|\D)([01])(?:\D|$)");
            return match.Success ? match.Groups[1].Value : "";
        }

        private void TestGsensor()
        {
            GsensorMovementTracker tracker = new GsensorMovementTracker(GsensorDeltaThreshold);
            DateTime deadline = DateTime.UtcNow.AddMilliseconds(TestTimeoutMs(8));
            string lastResponse = "";
            string detected = "等待 GSENSOR 样本";
            SetTest(8, detected, "检测中", "请持续震动设备；工具每 250 ms 主动读取一次 XYZ");
            while (DateTime.UtcNow < deadline)
            {
                int remaining = (int)(deadline - DateTime.UtcNow).TotalMilliseconds;
                if (remaining <= 0) break;
                lastResponse = FactoryQuery("GSENSOR#", Math.Min(900, remaining));
                if (lastResponse.Length == 0) continue;
                ProductionReply reply;
                if (ProductionReply.TryParse(lastResponse, "GSENSOR", out reply) && !reply.Success)
                {
                    SetFactoryTest(8, lastResponse, "不通过", "G-sensor 驱动读取失败：" + reply.ErrorCode,
                        lastResponse, FailureClass.FirmwareDriverFailure, "");
                    return;
                }
                FactoryGsensor sample;
                if (!FactoryMeasurements.TryParseGsensor(lastResponse, out sample))
                {
                    SetFactoryTest(8, lastResponse, "不通过", "GSENSOR 响应格式无效",
                        lastResponse, FailureClass.FirmwareDriverFailure, "");
                    return;
                }
                bool passed = tracker.Add(sample.X, sample.Y, sample.Z);
                detected = "X=" + sample.X + "；Y=" + sample.Y + "；Z=" + sample.Z +
                    "；INT=" + (sample.InterruptActive ? "1" : "0") + "；样本=" + tracker.SampleCount +
                    "；三轴总变化=" + tracker.MaxDelta;
                if (passed)
                {
                    SetFactoryTest(8, detected, "通过", "XYZ 总变化达到阈值 " + GsensorDeltaThreshold,
                        lastResponse, FailureClass.None, "");
                    return;
                }
                SetTest(8, detected, "检测中", "继续震动设备，阈值=" + GsensorDeltaThreshold);
                Thread.Sleep(Math.Min(250, Math.Max(1, remaining)));
            }
            FailureClass failure = tracker.SampleCount == 0 ? FailureClass.CommunicationTimeout : FailureClass.MeasurementOutOfRange;
            SetFactoryTest(8, detected, "不通过", tracker.SampleCount == 0 ? "GSENSOR 两次尝试均无关联响应" : "有效样本不足或变化未达到阈值",
                lastResponse, failure, "");
        }

        private void TestVoltage()
        {
            DateTime deadline = DateTime.UtcNow.AddMilliseconds(TestTimeoutMs(9));
            string response = "";
            FactoryVoltage voltage = new FactoryVoltage();
            bool haveVoltage = false;
            while (DateTime.UtcNow < deadline)
            {
                int remaining = (int)(deadline - DateTime.UtcNow).TotalMilliseconds;
                if (remaining <= 0) break;
                response = FactoryQuery("STATUS#", Math.Min(900, remaining));
                if (FactoryMeasurements.TryParseVoltage(response, out voltage) && voltage.Valid)
                {
                    haveVoltage = true;
                    break;
                }
                ProductionReply reply;
                if (ProductionReply.TryParse(response, "STATUS", out reply) && !reply.Success && reply.ErrorCode != "ADC_NOT_READY")
                {
                    SetFactoryTest(9, response, "不通过", "电压驱动失败：" + reply.ErrorCode,
                        response, FailureClass.FirmwareDriverFailure, "");
                    return;
                }
                Thread.Sleep(Math.Min(100, Math.Max(1, remaining)));
            }
            double min, max;
            ParseDoublePair(TestValue(9), out min, out max);
            if (!haveVoltage)
            {
                FailureClass failure = response.Length == 0 ? FailureClass.CommunicationTimeout : FailureClass.FirmwareDriverFailure;
                SetFactoryTest(9, response.Length == 0 ? "无 STATUS 响应" : response, "不通过",
                    response.Length == 0 ? "STATUS 两次尝试均无关联响应" : "ADC 在测试超时内未就绪",
                    response, failure, "");
                return;
            }
            _latestCarVoltage = voltage.CarMillivolts / 1000.0;
            bool ok = FactoryMeasurements.VoltageInRange(voltage.CarMillivolts, (decimal)min, (decimal)max);
            string detected = "VCAR=" + voltage.CarMillivolts + " mV；VBAT=" + voltage.BatteryMillivolts + " mV";
            SetFactoryTest(9, detected, ok ? "通过" : "不通过", "允许范围 " + min + "-" + max + " V（含边界）",
                response, ok ? FailureClass.None : FailureClass.MeasurementOutOfRange, "");
        }

        private void TestRelay()
        {
            int timeout = TestTimeoutMs(10);
            List<string> results = new List<string>();
            _relayTestMayBeLow = true;
            try
            {
                for (int cycle = 1; cycle <= 2; cycle++)
                {
                    string low = Command("RELAYTEST,LOW#", timeout);
                    results.Add("低" + cycle + "=" + (low.Length == 0 ? "超时" : low));
                    FactoryRelay lowState;
                    if (!FactoryMeasurements.TryParseRelay(low, out lowState) || !lowState.ExternalLow || !lowState.McuAsserted || !lowState.PadAsserted)
                    {
                        FailureClass failure = low.Length == 0 ? FailureClass.CommunicationTimeout : FailureClass.FirmwareDriverFailure;
                        string status = low.Length == 0 ? FactoryQuery("RELAYTEST,STATUS#", 900) : "";
                        if (status.Length > 0) results.Add("状态=" + status);
                        SetFactoryTest(10, string.Join("；", results.ToArray()), "不通过",
                            low.Length == 0 ? "LOW 响应不明确，已查询状态并强制恢复 HIGH" : "LOW 的 MCU/PAD 诊断状态不一致",
                            low + " " + status, failure, "");
                        return;
                    }
                    Thread.Sleep(700);
                    string high = Command("RELAYTEST,HIGH#", timeout);
                    results.Add("高" + cycle + "=" + (high.Length == 0 ? "超时" : high));
                    FactoryRelay highState;
                    if (!FactoryMeasurements.TryParseRelay(high, out highState) || highState.ExternalLow || highState.McuAsserted || highState.PadAsserted)
                    {
                        FailureClass failure = high.Length == 0 ? FailureClass.CommunicationTimeout : FailureClass.FirmwareDriverFailure;
                        SetFactoryTest(10, string.Join("；", results.ToArray()), "不通过",
                            "HIGH 未获明确安全状态，退出前将再次恢复", high, failure, "");
                        return;
                    }
                    _relayTestMayBeLow = false;
                    if (cycle < 2) Thread.Sleep(500);
                    _relayTestMayBeLow = true;
                }
                SetFactoryTest(10, string.Join("；", results.ToArray()), "待人工",
                    "请确认治具两轮均观察到外部 LOW 后恢复 HIGH", string.Join(" | ", results.ToArray()),
                    FailureClass.PendingOperatorConfirmation, "待确认");
            }
            finally
            {
                TryRestoreRelayHigh();
            }
        }

        private void TestTts()
        {
            byte[] wire;
            string validationError;
            if (!GbkTtsValidator.BuildWireCommand(TestValue(12), out wire, out validationError))
            {
                SetFactoryTest(12, validationError, "不通过", "播报文本必须为 1-160 GBK 字节且不得包含分隔符",
                    "", FailureClass.MeasurementOutOfRange, "");
                return;
            }
            string response = CommandBytes("TTS", wire, TestTimeoutMs(12));
            ProductionReply reply;
            if (response.Length == 0)
            {
                SetFactoryTest(12, "无响应", "不通过", "TTS 命令通信超时", response,
                    FailureClass.CommunicationTimeout, "");
                return;
            }
            if (!ProductionReply.TryParse(response, "TTS", out reply) || !reply.Success)
            {
                SetFactoryTest(12, response, "不通过", "TTS 启动失败" + (reply == null ? "" : "：" + reply.ErrorCode),
                    response, FailureClass.FirmwareDriverFailure, "");
                return;
            }
            SetFactoryTest(12, response, "待人工", "请确认扬声器播报清晰可辨，再进行人工判定",
                response, FailureClass.PendingOperatorConfirmation, "待确认");
        }

        private void TestRs485()
        {
            SetFactoryTest(14, "V1.281: RS485=0", "跳过", "本版本未纳入 RS485 生产测试",
                _latestCapabilityResponse, FailureClass.SkippedNotTested, "");
        }

        private void RunSelectedTest()
        {
            if (_grid.SelectedRows.Count == 0) return;
            EnsureActiveRecordForCurrentFields();
            int no = Convert.ToInt32(_grid.SelectedRows[0].Cells[0].Value);
            SyncTestPresetsFromParameters();
            lock (_recordLock)
            {
                _tests[no].RawResponse = "";
                _tests[no].FailureReason = "";
                _tests[no].OperatorConfirmation = "";
            }
            RunWorker(delegate
            {
                string param = Command("PARAM#", 3500);
                Dictionary<string, string> p = ParseParam(param);
                if (p.Count == 0) { SetTest(no, "无 PARAM 响应", "不通过", "无法开始检测"); return; }
                _latestImei = Get(p, "IMEI");
                if ((no == 7 || no == 8 || no == 9 || no == 10 || no == 12) &&
                    (!LoadFactoryCapabilities() || !CapabilitySupported(no)))
                {
                    SetUnsupportedFactoryTest(no, _latestCapabilityResponse);
                    return;
                }
                if (no == 10 && !TryRestoreRelayHigh())
                {
                    SetFactoryTest(10, "无法确认 RELAY HIGH", "不通过", "安全前置条件失败",
                        _latestCapabilityResponse, FailureClass.FirmwareDriverFailure, "");
                    return;
                }
                switch (no)
                {
                    case 1: TestVersion(p); break;
                    case 2: TestServers(p); break;
                    case 3: TestTerminalId(p); break;
                    case 4: TestSim(p); break;
                    case 5: TestCsq(p); break;
                    case 6: TestGps(p); break;
                    case 7: TestAcc(p); break;
                    case 8: TestGsensor(); break;
                    case 9: TestVoltage(); break;
                    case 10: TestRelay(); break;
                    case 11: SetTest(11, "等待 SOS 触发", "待人工", "SOS 接地保持 " + TestValue(11) + " 秒"); break;
                    case 12: TestTts(); break;
                    case 13: SetTest(13, "PARAM 双向收发成功", "通过", "调试 UART 正常"); break;
                    case 14: TestRs485(); break;
                }
                UpdateSummary();
            });
        }

        private void ManualResult(string result)
        {
            if (_grid.SelectedRows.Count == 0) return;
            int no = Convert.ToInt32(_grid.SelectedRows[0].Cells[0].Value);
            TestItem item = _tests[no];
            if (item.Result != "待人工")
            {
                MessageBox.Show("只有状态为“待人工”的项目可以人工判定。通信、固件/驱动和测量失败必须重新测试。", "人工判定", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            FailureClass failure = result == "通过" ? FailureClass.None : FailureClass.HardwareFailure;
            SetFactoryTest(no, item.Detected, result, item.Note + "（人工判定）",
                item.RawResponse, failure, result == "通过" ? "操作员确认通过" : "操作员确认不通过");
            UpdateSummary();
        }

        private void SetTest(int number, string detected, string result, string note)
        {
            TestItem item = _tests[number];
            lock (_recordLock)
            {
                item.Detected = detected;
                item.Result = result;
                item.Note = note;
            }
            Ui(delegate
            {
                DataGridViewRow row = _grid.Rows[number - 1];
                row.Cells[5].Value = CurrentTarget(number);
                row.Cells[7].Value = result;
                row.Cells[8].Value = detected;
                row.Cells[9].Value = note;
                _grid.InvalidateRow(number - 1);
            });
            if (result != "检测中" && result != "等待") PersistRealtimeRecord();
        }

        private void SetTestThreadSafe(int number, string detected, string result, string note)
        {
            if (!IsHandleCreated) return;
            BeginInvoke((MethodInvoker)delegate { SetTest(number, detected, result, note); UpdateSummary(); });
        }

        private string CurrentTarget(int number)
        {
            return TestValue(number);
        }

        private void UpdateSummary()
        {
            Ui(delegate
            {
                int pass = 0, fail = 0, pending = 0;
                foreach (TestItem t in _tests.Values)
                {
                    if (t.Result == "通过") pass++;
                    else if (t.Result == "不通过") fail++;
                    else pending++;
                }
                _summary.Text = string.Format("通过 {0} 项 / 不通过 {1} 项 / 待测或待人工 {2} 项", pass, fail, pending);
                _summary.ForeColor = fail > 0 ? Color.Firebrick : (pending > 0 ? Color.DarkOrange : Color.SeaGreen);
            });
        }

        private void GridCellFormatting(object sender, DataGridViewCellFormattingEventArgs e)
        {
            if (e.ColumnIndex != 7 || e.Value == null) return;
            string value = e.Value.ToString();
            if (value == "通过") e.CellStyle.ForeColor = Color.SeaGreen;
            else if (value == "不通过") e.CellStyle.ForeColor = Color.Firebrick;
            else if (value == "待人工") e.CellStyle.ForeColor = Color.DarkOrange;
            if (value == "通过") e.CellStyle.BackColor = Color.FromArgb(205, 245, 215);
            else if (value == "不通过") e.CellStyle.BackColor = Color.FromArgb(255, 215, 215);
            else if (value == "等待" || value == "待人工") e.CellStyle.BackColor = Color.FromArgb(255, 245, 170);
            else if (value == "检测中") e.CellStyle.BackColor = Color.FromArgb(210, 235, 255);
            else if (value == "跳过") e.CellStyle.BackColor = Color.Gainsboro;
            e.CellStyle.Font = new Font(_grid.Font, FontStyle.Bold);
        }

        private void SendCustomCommand()
        {
            if (!_serial.IsOpen) { MessageBox.Show("请先连接设备。", "A300"); return; }
            string cmd = _customCommand.Text.Trim();
            if (cmd.Length == 0) return;
            RunWorker(delegate { Command(cmd, 3500); });
        }

        private void PrepareActiveRecord(Dictionary<string, string> values)
        {
            string orderNo = values["order_no"];
            string id = values["terminal_id"].Length > 0 ? values["terminal_id"] : "unknown";
            DateTime startedAt;
            lock (_recordLock) startedAt = _recordStartedAt;
            string dir = Path.Combine(_baseDir, "records", SafeFileName(orderNo), startedAt.ToString("yyyyMMdd"));
            Directory.CreateDirectory(dir);
            string baseName = startedAt.ToString("yyyyMMdd_HHmmss_fff") + "_" + SafeFileName(id);
            lock (_recordLock)
            {
                _activeOrderNo = orderNo;
                _activeSummaryPath = Path.Combine(dir, baseName + "_汇总.csv");
                _activeDetailPath = Path.Combine(dir, baseName + "_测试明细.csv");
            }
        }

        private void EnsureActiveRecordForCurrentFields()
        {
            Dictionary<string, string> values = SnapshotFields();
            if (!_orderReady || !ValidOrderNumber(values["order_no"])) throw new InvalidOperationException("请先新建或加载订单。 ");
            if (values["terminal_id"].Length == 0) throw new InvalidOperationException("请先扫码或填写终端ID。 ");
            lock (_recordLock)
            {
                if (_activeSummaryPath.Length > 0 &&
                    string.Equals(_activeOrderNo, values["order_no"], StringComparison.OrdinalIgnoreCase) &&
                    string.Equals(_recordTerminalId, values["terminal_id"], StringComparison.Ordinal)) return;
            }
            lock (_recordLock)
            {
                _recordStartedAt = DateTime.Now;
                _recordTerminalId = values["terminal_id"];
                _recordImeiInput = values["imei_input"];
                _recordWriteSummary = "未执行参数写入";
                _recordParameters.Clear();
                foreach (KeyValuePair<string, string> pair in values) _recordParameters[pair.Key] = pair.Value;
                _recordWriteResults.Clear();
            }
            PrepareActiveRecord(values);
            PersistRealtimeRecord();
        }

        private void PersistRealtimeRecord()
        {
            string summaryPath, detailPath, orderNo, id, imeiInput, writeSummary;
            DateTime startedAt;
            Dictionary<string, string> written = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            Dictionary<string, string> writeResults = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            List<TestItem> tests = new List<TestItem>();
            lock (_recordLock)
            {
                summaryPath = _activeSummaryPath;
                detailPath = _activeDetailPath;
                orderNo = _activeOrderNo;
                if (summaryPath.Length == 0 || detailPath.Length == 0) return;
                startedAt = _recordStartedAt;
                id = _recordTerminalId;
                imeiInput = _recordImeiInput;
                writeSummary = _recordWriteSummary;
                foreach (KeyValuePair<string, string> pair in _recordParameters) written[pair.Key] = pair.Value;
                foreach (KeyValuePair<string, string> pair in _recordWriteResults) writeResults[pair.Key] = pair.Value;
                for (int i = 1; i <= 14; i++)
                {
                    TestItem t = _tests[i];
                    tests.Add(new TestItem { Number = t.Number, Code = t.Code, Name = t.Name, Enabled = t.Enabled, Parameter = t.Parameter, Value = t.Value, TimeoutSeconds = t.TimeoutSeconds, Detected = t.Detected, Result = t.Result, Note = t.Note, RawResponse = t.RawResponse, FailureReason = t.FailureReason, OperatorConfirmation = t.OperatorConfirmation });
                }
            }

            try
            {
                lock (_recordFileLock)
                {
                    Dictionary<string, string> actual = ParseParam(_latestParam);
                    if (id.Length == 0) id = Get(actual, "PID");
                    if (id.Length == 0) id = "unknown";
                    string imei = _latestImei.Length > 0 ? _latestImei : (Get(actual, "IMEI").Length > 0 ? Get(actual, "IMEI") : imeiInput);
                    DateTime savedAt = DateTime.Now;
                    List<string> headers = new List<string> {
                        "订单号", "测试时间", "测试结果", "终端ID", "IMEI", "ICCID", "软件版本号", "固件完整版本", "固件语义版本", "生产接口能力版本", "测试工具版本", "操作员工号", "设备终端型号", "GPS", "SIM卡信号强度", "主电",
                        "设备主平台", "设备副平台", "设备上报间隔", "写入IMEI/扫码值", "写入终端ID", "写入终端型号",
                        "写入主平台IP/域名", "写入主平台端口", "写入副平台IP/域名", "写入副平台端口",
                        "写入APN", "写入APN用户名", "写入APN密码", "写入ACC ON间隔(s)", "写入ACC OFF间隔(s)",
                        "写入RTK服务IP/域名", "写入RTK端口", "写入RTK账号", "写入RTK密码", "写入RTK挂载点",
                        "IMEI校验结果", "主平台写入结果", "副平台写入结果", "终端ID写入结果", "终端型号写入结果", "APN写入结果", "上报间隔写入结果", "RTK写入结果", "参数写入总结果"
                    };
                    List<string> values = new List<string> {
                        orderNo, startedAt.ToString("yyyy-MM-dd HH:mm:ss"), OverallTestResult(writeSummary, tests), id, imei, Get(actual, "ICCID"), Get(actual, "VER"),
                        _firmwareFullVersion, _firmwareSemanticVersion, _factoryCapabilityVersion, TesterVersion, _settings.Get("operator_id", ""),
                        Get(actual, "MODEL"), Get(actual, "GPS"), Get(actual, "CSQ"), _latestCarVoltage < 0 ? "" : _latestCarVoltage.ToString("0.0", CultureInfo.InvariantCulture) + " V",
                        Get(actual, "IP"), Get(actual, "FIP"), Get(actual, "FORCE"), imeiInput, RecordValue(written, "terminal_id"), RecordValue(written, "terminal_model"),
                        RecordValue(written, "main_ip"), RecordValue(written, "main_port"), RecordValue(written, "backup_ip"), RecordValue(written, "backup_port"),
                        RecordValue(written, "apn"), RecordValue(written, "apn_user"), RecordValue(written, "apn_pass"), RecordValue(written, "acc_on_interval"), RecordValue(written, "acc_off_interval"),
                        RecordValue(written, "rtk_ip"), RecordValue(written, "rtk_port"), RecordValue(written, "rtk_user"), RecordValue(written, "rtk_pass"), RecordValue(written, "rtk_mount"),
                        RecordValue(writeResults, "IMEI校验"), RecordValue(writeResults, "主平台"), RecordValue(writeResults, "副平台"), RecordValue(writeResults, "终端ID"), RecordValue(writeResults, "终端型号"),
                        RecordValue(writeResults, "APN"), RecordValue(writeResults, "上报间隔"), RecordValue(writeResults, "RTK"), writeSummary
                    };
                    foreach (TestItem t in tests) { headers.Add(t.Name); values.Add(TestRecordValue(t)); }
                    headers.Add("更新时间");
                    values.Add(savedAt.ToString("yyyy-MM-dd HH:mm:ss"));
                    WriteAllLinesAtomic(summaryPath, new[] { JoinCsv(headers), JoinCsv(values) });

                    List<string> lines = new List<string>();
                    lines.Add("订单号,时间,终端ID,IMEI,固件完整版本,固件语义版本,生产接口能力版本,测试工具版本,操作员工号,参数写入总结果,写入参数明细,序号,测试项目,预设/门限,检测值,结果,失败分类,原始命令响应,人工确认,说明");
                    string parameterSummary = WrittenParameterSummary(written);
                    foreach (TestItem t in tests)
                        lines.Add(JoinCsv(new[] { orderNo, startedAt.ToString("yyyy-MM-dd HH:mm:ss"), id, imei, _firmwareFullVersion, _firmwareSemanticVersion, _factoryCapabilityVersion, TesterVersion, _settings.Get("operator_id", ""), writeSummary, parameterSummary, t.Number.ToString(), t.Name, t.Value, t.Detected, t.Result, t.FailureReason, t.RawResponse, t.OperatorConfirmation, t.Note }));
                    WriteAllLinesAtomic(detailPath, lines.ToArray());
                }
                SetRecordState("本机记录已实时保存：" + summaryPath, Color.SeaGreen);
                QueueRecordSync(orderNo, summaryPath, detailPath);
            }
            catch (Exception ex)
            {
                SetRecordState("实时保存失败：" + ex.Message, Color.Firebrick);
            }
        }

        private static string OverallTestResult(string writeSummary, List<TestItem> tests)
        {
            if ((writeSummary ?? "").StartsWith("参数写入失败", StringComparison.Ordinal)) return "参数写入失败";
            if ((writeSummary ?? "").StartsWith("执行异常", StringComparison.Ordinal)) return "执行异常";
            bool pending = false;
            foreach (TestItem item in tests)
            {
                if (!item.Enabled || item.Result == "跳过") continue;
                if (item.Result == "不通过") return "测试失败";
                if (item.Result != "通过") pending = true;
            }
            return pending ? "测试未完成" : "测试成功";
        }

        private static string TestRecordValue(TestItem item)
        {
            string text = item.Result;
            if (!string.IsNullOrEmpty(item.Detected)) text += "：" + item.Detected;
            if (!string.IsNullOrEmpty(item.FailureReason)) text += "；分类=" + item.FailureReason;
            if (!string.IsNullOrEmpty(item.OperatorConfirmation)) text += "；人工=" + item.OperatorConfirmation;
            if (!string.IsNullOrEmpty(item.Note)) text += "；" + item.Note;
            return text;
        }

        private static string WrittenParameterSummary(Dictionary<string, string> values)
        {
            return "终端ID=" + RecordValue(values, "terminal_id") +
                "；终端型号=" + RecordValue(values, "terminal_model") +
                "；主平台=" + HostPort(values, "main_ip", "main_port") +
                "；副平台=" + HostPort(values, "backup_ip", "backup_port") +
                "；APN=" + RecordValue(values, "apn") + "," + RecordValue(values, "apn_user") + "," + RecordValue(values, "apn_pass") +
                "；上报间隔=" + RecordValue(values, "acc_on_interval") + ":" + RecordValue(values, "acc_off_interval") +
                "；RTK=" + HostPort(values, "rtk_ip", "rtk_port") + "," + RecordValue(values, "rtk_mount") + "," + RecordValue(values, "rtk_user") + "," + RecordValue(values, "rtk_pass");
        }

        private static string HostPort(Dictionary<string, string> values, string hostKey, string portKey)
        {
            string host = RecordValue(values, hostKey);
            string port = RecordValue(values, portKey);
            return host.Length == 0 && port.Length == 0 ? "" : host + ":" + port;
        }

        private static string RecordValue(Dictionary<string, string> values, string key)
        {
            string value;
            return values != null && values.TryGetValue(key, out value) ? value ?? "" : "";
        }

        private static void WriteAllLinesAtomic(string path, string[] lines)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            string temp = path + ".tmp";
            File.WriteAllLines(temp, lines, new UTF8Encoding(true));
            if (!File.Exists(path))
            {
                File.Move(temp, path);
                return;
            }
            try { File.Replace(temp, path, null); }
            catch
            {
                File.Copy(temp, path, true);
                File.Delete(temp);
            }
        }

        private void QueueRecordSync(string orderNo, string summaryPath, string detailPath)
        {
            RecordSyncJob job = new RecordSyncJob { OrderNo = orderNo, SummaryPath = summaryPath, DetailPath = detailPath };
            Ui(delegate
            {
                job.ShareEnabled = _shareEnabled.Checked;
                job.SharePath = _sharePath.Text.Trim();
                job.FtpEnabled = _ftpEnabled.Checked;
                job.FtpUrl = _ftpUrl.Text.Trim();
                job.FtpUser = _ftpUser.Text.Trim();
                job.FtpPassword = _ftpPassword.Text;
                job.HttpEnabled = _httpEnabled.Checked;
                job.HttpUrl = _httpUrl.Text.Trim();
                job.HttpToken = _httpToken.Text.Trim();
            });
            if (!job.ShareEnabled && !job.FtpEnabled && !job.HttpEnabled) return;
            lock (_syncLock)
            {
                _pendingSyncJob = job;
                if (_syncWorkerRunning) return;
                _syncWorkerRunning = true;
            }
            Task.Factory.StartNew(ProcessRecordSyncQueue);
        }

        private void ProcessRecordSyncQueue()
        {
            while (true)
            {
                RecordSyncJob job;
                lock (_syncLock)
                {
                    job = _pendingSyncJob;
                    _pendingSyncJob = null;
                    if (job == null)
                    {
                        _syncWorkerRunning = false;
                        return;
                    }
                }
                SyncRecordJob(job);
            }
        }

        private void SyncRecordJob(RecordSyncJob job)
        {
            List<string> errors = new List<string>();
            if (job.ShareEnabled)
            {
                try
                {
                    if (job.SharePath.Length == 0) throw new InvalidOperationException("共享目录为空");
                    string date = Path.GetFileName(Path.GetDirectoryName(job.SummaryPath));
                    string targetDir = Path.Combine(job.SharePath, SafeFileName(job.OrderNo), date);
                    Directory.CreateDirectory(targetDir);
                    File.Copy(job.SummaryPath, Path.Combine(targetDir, Path.GetFileName(job.SummaryPath)), true);
                    File.Copy(job.DetailPath, Path.Combine(targetDir, Path.GetFileName(job.DetailPath)), true);
                }
                catch (Exception ex) { errors.Add("共享目录：" + ex.Message); }
            }
            if (job.FtpEnabled)
            {
                try
                {
                    if (!job.FtpUrl.StartsWith("ftp://", StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("FTP地址必须以 ftp:// 开头");
                    UploadFtpFile(job, job.SummaryPath);
                    UploadFtpFile(job, job.DetailPath);
                }
                catch (Exception ex) { errors.Add("FTP：" + ex.Message); }
            }
            if (job.HttpEnabled)
            {
                try
                {
                    Uri uri;
                    if (!Uri.TryCreate(job.HttpUrl, UriKind.Absolute, out uri) || (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps))
                        throw new InvalidOperationException("服务器地址必须为 http:// 或 https://");
                    UploadHttpFile(job, job.SummaryPath, "summary");
                    UploadHttpFile(job, job.DetailPath, "detail");
                }
                catch (Exception ex) { errors.Add("HTTP：" + ex.Message); }
            }
            if (errors.Count == 0) SetRecordState("本机记录及远程目标均已同步", Color.SeaGreen);
            else SetRecordState("本机已保存，远程同步失败：" + string.Join("；", errors.ToArray()), Color.DarkOrange);
        }

        private static void UploadFtpFile(RecordSyncJob job, string localPath)
        {
            string remoteName = SafeFileName(job.OrderNo) + "_" + Path.GetFileName(localPath);
            string url = job.FtpUrl.TrimEnd('/') + "/" + Uri.EscapeDataString(remoteName);
            FtpWebRequest request = (FtpWebRequest)WebRequest.Create(url);
            request.Method = WebRequestMethods.Ftp.UploadFile;
            request.UseBinary = true;
            request.KeepAlive = false;
            request.Timeout = 15000;
            request.ReadWriteTimeout = 15000;
            request.Credentials = new NetworkCredential(job.FtpUser, job.FtpPassword);
            using (FileStream input = File.OpenRead(localPath))
            using (Stream output = request.GetRequestStream()) input.CopyTo(output);
            using (FtpWebResponse response = (FtpWebResponse)request.GetResponse()) { }
        }

        private static void UploadHttpFile(RecordSyncJob job, string localPath, string kind)
        {
            using (WebClient client = new WebClient())
            {
                client.Headers["X-Order-No"] = job.OrderNo;
                client.Headers["X-Record-Kind"] = kind;
                if (job.HttpToken.Length > 0) client.Headers[HttpRequestHeader.Authorization] = "Bearer " + job.HttpToken;
                client.UploadFile(job.HttpUrl, "POST", localPath);
            }
        }

        private static string JoinCsv(IEnumerable<string> values)
        {
            List<string> cells = new List<string>();
            foreach (string value in values) cells.Add(Csv(value));
            return string.Join(",", cells.ToArray());
        }

        private void LoadSettingsToUi()
        {
            _syncImeiTerminal.Checked = _settings.Get("sync_imei_terminal", "0") == "1";
            foreach (KeyValuePair<string, TextBox> pair in _fields)
            {
                if (pair.Key == "order_no") pair.Value.Clear();
                else pair.Value.Text = _settings.Get(pair.Key, pair.Value.Text);
            }
            _orderReady = false;
            if (_fields["identity"].Text.Length == 0) _fields["identity"].Text = _settings.Get("terminal_id", "");
            if (_fields["backup_ip"].Text.Length == 0 && _fields["backup_port"].Text == "0") _fields["backup_port"].Text = "";
            if (_fields["rtk_ip"].Text.Length == 0 && _fields["rtk_port"].Text == "0") _fields["rtk_port"].Text = "";
            bool hasRtk = _fields["rtk_ip"].Text.Length > 0 || _fields["rtk_user"].Text.Length > 0 || _fields["rtk_pass"].Text.Length > 0 || _fields["rtk_mount"].Text.Length > 0;
            SetRtkWriteEnabled(_settings.Get("rtk_write_enabled", hasRtk ? "1" : "0") == "1");
            _scanAutoWorkflow.Checked = _settings.Get("scan_auto_workflow", "1") == "1";
            _shareEnabled.Checked = _settings.Get("record_share_enabled", "0") == "1";
            _sharePath.Text = _settings.Get("record_share_path", "");
            _ftpEnabled.Checked = _settings.Get("record_ftp_enabled", "0") == "1";
            _ftpUrl.Text = _settings.Get("record_ftp_url", "");
            _ftpUser.Text = _settings.Get("record_ftp_user", "");
            _ftpPassword.Text = _settings.Get("record_ftp_password", "");
            _httpEnabled.Checked = _settings.Get("record_http_enabled", "0") == "1";
            _httpUrl.Text = _settings.Get("record_http_url", "");
            _httpToken.Text = _settings.Get("record_http_token", "");
            string baud = _settings.Get("baud", "115200");
            if (_baud.Items.Contains(baud)) _baud.SelectedItem = baud;
        }

        private void SaveUiSettings()
        {
            SyncTestsFromGrid();
            foreach (KeyValuePair<string, TextBox> pair in _fields)
            {
                if (pair.Key == "order_no") continue;
                bool importedRtk = _rtkExcelPath.Length > 0 && (pair.Key == "rtk_ip" || pair.Key == "rtk_port" || pair.Key == "rtk_user" || pair.Key == "rtk_pass" || pair.Key == "rtk_mount");
                _settings.Set(pair.Key, importedRtk ? "" : pair.Value.Text.Trim());
            }
            _settings.Set("order_no", "");
            foreach (TestItem item in _tests.Values)
            {
                _settings.Set("test_" + item.Number + "_enabled", item.Enabled ? "1" : "0");
                _settings.Set("test_" + item.Number + "_value", item.Value);
                _settings.Set("test_" + item.Number + "_timeout", item.TimeoutSeconds.ToString());
            }
            _settings.Set("sync_imei_terminal", _syncImeiTerminal.Checked ? "1" : "0");
            _settings.Set("scan_auto_workflow", _scanAutoWorkflow.Checked ? "1" : "0");
            _settings.Set("rtk_write_enabled", RtkWriteEnabled() ? "1" : "0");
            _settings.Set("rtk_excel_path", _rtkExcelPath);
            _settings.Set("rtk_excel_fingerprint", _rtkExcelFingerprint);
            _settings.Set("rtk_excel_next_index", _rtkNextIndex.ToString(CultureInfo.InvariantCulture));
            _settings.Set("record_share_enabled", _shareEnabled.Checked ? "1" : "0");
            _settings.Set("record_share_path", _sharePath.Text.Trim());
            _settings.Set("record_ftp_enabled", _ftpEnabled.Checked ? "1" : "0");
            _settings.Set("record_ftp_url", _ftpUrl.Text.Trim());
            _settings.Set("record_ftp_user", _ftpUser.Text.Trim());
            _settings.Set("record_ftp_password", _ftpPassword.Text);
            _settings.Set("record_http_enabled", _httpEnabled.Checked ? "1" : "0");
            _settings.Set("record_http_url", _httpUrl.Text.Trim());
            _settings.Set("record_http_token", _httpToken.Text.Trim());
            _settings.Set("baud", _baud.SelectedItem == null ? "115200" : _baud.SelectedItem.ToString());
            _settings.Save();
        }

        private void MainFormClosing(object sender, FormClosingEventArgs e)
        {
            try { SaveUiSettings(); } catch { }
            TryRestoreRelayHigh();
            _serial.Dispose();
        }

        private Dictionary<string, string> SnapshotFields()
        {
            Dictionary<string, string> values = new Dictionary<string, string>();
            Ui(delegate { foreach (KeyValuePair<string, TextBox> pair in _fields) values[pair.Key] = pair.Value.Text.Trim(); });
            if (values["backup_ip"].Length == 0 && values["backup_port"] == "0") values["backup_port"] = "";
            if (values["rtk_ip"].Length == 0 && values["rtk_port"] == "0") values["rtk_port"] = "";
            string identity = values["identity"];
            bool syncImei = SyncImeiTerminalEnabled();
            values["terminal_id"] = syncImei && identity.Length >= 11 ? identity.Substring(identity.Length - 11) : identity;
            values["imei_input"] = syncImei && identity.Length == 15 ? identity : "";
            return values;
        }

        private string ExpectedTerminalId()
        {
            string identity = Field("identity");
            return SyncImeiTerminalEnabled() && identity.Length >= 11 ? identity.Substring(identity.Length - 11) : identity;
        }

        private bool SyncImeiTerminalEnabled()
        {
            if (InvokeRequired)
            {
                bool enabled = false;
                Invoke((MethodInvoker)delegate { enabled = _syncImeiTerminal.Checked; });
                return enabled;
            }
            return _syncImeiTerminal.Checked;
        }

        private bool RtkWriteEnabled()
        {
            if (InvokeRequired)
            {
                bool enabled = false;
                Invoke((MethodInvoker)delegate { enabled = RtkWriteEnabled(); });
                return enabled;
            }
            foreach (CheckBox check in _rtkWriteChecks.Values) if (!check.Checked) return false;
            return _rtkWriteChecks.Count > 0;
        }

        private string Field(string key)
        {
            if (InvokeRequired)
            {
                string value = "";
                Invoke((MethodInvoker)delegate { value = _fields[key].Text.Trim(); });
                return value;
            }
            return _fields[key].Text.Trim();
        }

        private void Ui(MethodInvoker action)
        {
            if (IsDisposed) return;
            if (InvokeRequired) Invoke(action); else action();
        }

        private static Dictionary<string, string> ParseParam(string response)
        {
            Dictionary<string, string> values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (Match m in Regex.Matches(response ?? "", @"([A-Z]+)\[([^\]]*)\]", RegexOptions.IgnoreCase)) values[m.Groups[1].Value] = m.Groups[2].Value;
            return values;
        }

        private static string Get(Dictionary<string, string> values, string key)
        {
            string value;
            return values.TryGetValue(key, out value) ? value : "";
        }

        private void SetHostPortFields(string value, string hostKey, string portKey)
        {
            int p = value.LastIndexOf(':');
            if (p > 0)
            {
                string host = value.Substring(0, p);
                string port = value.Substring(p + 1);
                if ((host.Length == 0 || host == "0") && port == "0") { host = ""; port = ""; }
                _fields[hostKey].Text = host;
                _fields[portKey].Text = port;
            }
        }

        private static bool IsSuccess(string response)
        {
            return response != null && response.IndexOf("=Success", StringComparison.OrdinalIgnoreCase) >= 0 && response.IndexOf("=Fail", StringComparison.OrdinalIgnoreCase) < 0;
        }

        private static string LastLine(string text)
        {
            if (string.IsNullOrEmpty(text)) return "无响应";
            string[] lines = text.Replace("\r", "").Split('\n');
            for (int i = lines.Length - 1; i >= 0; i--) if (lines[i].Trim().Length > 0) return lines[i].Trim();
            return text.Trim();
        }

        private static void ParseGpsThreshold(string text, out int minSats, out int minCn, out double maxHdop, out int stableSamples)
        {
            minSats = 6;
            minCn = 30;
            maxHdop = 2.5;
            stableSamples = 5;
            string[] parts = (text ?? "").Split('-', ',', '/');
            int value;
            double number;
            if (parts.Length > 0 && int.TryParse(parts[0], out value) && value >= 4 && value <= 20) minSats = value;
            if (parts.Length > 1 && int.TryParse(parts[1], out value) && value >= 20 && value <= 50) minCn = value;
            if (parts.Length > 2 && double.TryParse(parts[2], NumberStyles.Float, CultureInfo.InvariantCulture, out number) && number >= 0.5 && number <= 10.0) maxHdop = number;
            if (parts.Length > 3 && int.TryParse(parts[3], out value) && value >= 1 && value <= 20) stableSamples = value;
        }

        private static void ParseDoublePair(string text, out double a, out double b)
        {
            a = 9; b = 16;
            string[] parts = (text ?? "").Split('-', ',', '/');
            if (parts.Length > 0) double.TryParse(parts[0], NumberStyles.Float, CultureInfo.InvariantCulture, out a);
            if (parts.Length > 1) double.TryParse(parts[1], NumberStyles.Float, CultureInfo.InvariantCulture, out b);
        }

        private static string Csv(string text)
        {
            return "\"" + (text ?? "").Replace("\"", "\"\"").Replace("\r", " ").Replace("\n", " ") + "\"";
        }

        private static string SafeFileName(string text)
        {
            foreach (char c in Path.GetInvalidFileNameChars()) text = text.Replace(c, '_');
            return text;
        }
    }
}
