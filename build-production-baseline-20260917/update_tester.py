from pathlib import Path
root=Path(__file__).resolve().parents[2]/'生产测试工具/A300ProductionTester'
p=root/'src/A300ProductionTester.cs';s=p.read_text(encoding='utf-8-sig')
s=s.replace('1.5.0','1.6.0').replace('V1.281','V3.054')
s=s.replace('if (number == 14) enabled = false;', 'if (ProductionScope.IsExcluded(number)) enabled = false;')
s=s.replace('_grid.Rows.Add(number, code, name, enabled, parameter, value, timeout, "等待", "", note);','_grid.Rows.Add(number, code, name, enabled, parameter, value, timeout, "等待", "", note);\n            if (ProductionScope.IsExcluded(number)) _grid.Rows[number - 1].Cells[3].ReadOnly = true;')
s=s.replace('foreach (DataGridViewRow row in _grid.Rows) row.Cells[3].Value = enableAll;', 'foreach (DataGridViewRow row in _grid.Rows) row.Cells[3].Value = !ProductionScope.IsExcluded(Convert.ToInt32(row.Cells[0].Value)) && enableAll;')
s=s.replace('item.Enabled = Convert.ToBoolean(row.Cells[3].Value);','item.Enabled = !ProductionScope.IsExcluded(i) && Convert.ToBoolean(row.Cells[3].Value);\n                    row.Cells[3].Value = item.Enabled;')
s=s.replace('return _tests[number].Enabled;', 'return !ProductionScope.IsExcluded(number) && _tests[number].Enabled;')
s=s.replace('            if (data.IndexOf("[ALARM] SOS active", StringComparison.OrdinalIgnoreCase) >= 0) SetTestThreadSafe(11, "SOS active", "通过", "检测到 SOS 持续触发日志");','            // SOS results come only from the current SOSSTAT test window.')
s=s.replace('case 7: return _factoryCapabilities.Acc;', 'case 6: return _factoryCapabilities.Gnss;\n                case 11: return _factoryCapabilities.Sos;\n                case 7: return _factoryCapabilities.Acc;')
s=s.replace('return !_factoryCapabilities.Relay || TryRestoreRelayHigh();','return _factoryCapabilities.Relay && TryRestoreRelayHigh();')
s=s.replace('(i == 14 || !TestEnabled(i))', '(ProductionScope.IsExcluded(i) || !TestEnabled(i))')
s=s.replace('if (TestEnabled(6)) TestGps(p);','if (TestEnabled(6)) { if (factoryReady && CapabilitySupported(6)) TestGps(p); else SetUnsupportedFactoryTest(6, _latestCapabilityResponse); }')
s=s.replace('if (TestEnabled(11)) SetTest(11, "等待 SOS 触发", "待人工", "SOS 线接地保持 " + TestValue(11) + " 秒；检测到日志后自动通过");','if (TestEnabled(11)) { if (factoryReady && CapabilitySupported(11)) TestSos(); else SetUnsupportedFactoryTest(11, _latestCapabilityResponse); }')
s=s.replace('if (TestEnabled(12)) { if (factoryReady && CapabilitySupported(12)) TestTts(); else SetUnsupportedFactoryTest(12, _latestCapabilityResponse); }','SetExcludedTest(12);')
s=s.replace('(no == 7 || no == 8 || no == 9 || no == 10 || no == 12)', '(no == 6 || no == 7 || no == 8 || no == 9 || no == 10 || no == 11)')
s=s.replace('case 11: SetTest(11, "等待 SOS 触发", "待人工", "SOS 接地保持 " + TestValue(11) + " 秒"); break;', 'case 11: TestSos(); break;')
s=s.replace('case 12: TestTts(); break;', 'case 12: SetExcludedTest(12); break;')
s=s.replace('case 14: TestRs485(); break;', 'case 14: SetExcludedTest(14); break;')
s=s.replace('int no = Convert.ToInt32(_grid.SelectedRows[0].Cells[0].Value);\n            SyncTestPresetsFromParameters();','int no = Convert.ToInt32(_grid.SelectedRows[0].Cells[0].Value);\n            if (ProductionScope.IsExcluded(no)) { SetExcludedTest(no); return; }\n            SyncTestPresetsFromParameters();')
s=s.replace('if (!item.Enabled || item.Result == "跳过") continue;', 'if (ProductionScope.IsExcluded(item.Number) || !item.Enabled || item.Result == "跳过") continue;')
s=s.replace('min <= 33 && actual >= min && actual <= 33', 'min <= 31 && actual >= min && actual <= 31').replace('10-33','10-31')
s=s.replace('"SOS线接地保持"','"SOS线接地保持"')
s=s.replace('"等待SOS触发日志"','"先释放，再按下保持，轮询本次物理输入"')
s=s.replace('AddTest(12, "TTS", "TTS语音播报功能测试", "播报文本", "生产测试语音正常", 30, "操作员确认声音");','AddTest(12, "TTS", "TTS（不测试）", "本次范围", "未测试", 30, "按要求排除，不计通过");')
s=s.replace('"RS485串口功能测试"','"RS485（不测试）"')
s=s.replace('"必须接上天线且天线正常、有效定位、平均CN和HDOP连续达标"','"有效定位和新鲜GSV质量连续达标；不等价于天线电气开短路检测"')
# Scalar queries preserve the existing bounded PARAM/SMS wire contract.
s=s.replace('Dictionary<string, string> p = ParseParam(response);\n            if (p.Count == 0)', 'Dictionary<string, string> p = ParseParam(response);\n            string modelRead = Command("MODEL#", 1800);\n            Match modelMatch = Regex.Match(modelRead, @"^MODEL,([^=\\r\\n]+)=Success!", RegexOptions.IgnoreCase);\n            if (modelMatch.Success) p["MODEL"] = modelMatch.Groups[1].Value;\n            if (p.Count == 0)',1)
s=s.replace('string expectedApn = "APN," + v["apn"] + "," + v["apn_user"] + "," + v["apn_pass"] + "=Success";\n                if (apnVerify.IndexOf(expectedApn, StringComparison.OrdinalIgnoreCase) < 0)', 'if (!ProductionScope.ScalarMatches(apnVerify, "APN", v["apn"]))')
s=s.replace('else AppendWriteResult("APN", "复检通过");', 'else AppendWriteResult("APN", "APN名称复检通过；凭据仅核验写入应答，不回显");')
s=s.replace('Dictionary<string, string> p = ParseParam(verify);\n            if (Get(p, "IMEI").Length', 'Dictionary<string, string> p = ParseParam(verify);\n            if (writeModel && ProductionScope.ScalarMatches(Command("MODEL#", 1800), "MODEL", v["terminal_model"])) p["MODEL"] = v["terminal_model"];\n            if (Get(p, "IMEI").Length',1)
# Read APN response no longer contains credentials; do not clear order credentials.
a=s.index('            Match am = Regex.Match(apn,');b=s.index('            string rtk =',a)
s=s[:a]+'''            Match am = Regex.Match(apn, @"^APN,([^=,\\r\\n]+)=Success!", RegexOptions.IgnoreCase);
            if (am.Success) Ui(delegate { _fields["apn"].Text = am.Groups[1].Value; });
'''+s[b:]
s=s.replace('string rtk = Command("RTKINFO#", 1800);','string rtk = RtkWriteEnabled() ? Command("RTKINFO#", 1800) : "";')
# Replace old PARAM-derived GNSS quality and asynchronous SOS logging.
a=s.index('        private void TestGps(');b=s.index('        private void TestAcc(',a)
s=s[:a]+'''        private void SetExcludedTest(int number)
        {
            SetFactoryTest(number, "按要求排除", "跳过", "未测试，不计通过", "", FailureClass.SkippedNotTested, "");
        }

        private void TestSos()
        {
            int seconds;
            if (!int.TryParse(TestValue(11), out seconds) || seconds < 1 || seconds > 60)
                throw new InvalidOperationException("SOS 保持时间必须为 1–60 秒");
            var tracker = new SosHoldTracker(seconds * 1000);
            DateTime deadline = DateTime.UtcNow.AddMilliseconds(TestTimeoutMs(11));
            string response = "";
            while (_serial.IsOpen && DateTime.UtcNow < deadline)
            {
                SetTest(11, response, "检测中", "先释放 SOS，再接地保持 " + seconds + " 秒");
                response = FactoryQuery("SOSSTAT#", Math.Min(900, Math.Max(1, (int)(deadline - DateTime.UtcNow).TotalMilliseconds)));
                if (tracker.Observe(response))
                {
                    SetFactoryTest(11, response, "通过", "本次已观察释放及连续保持", response, FailureClass.None, "");
                    return;
                }
                Thread.Sleep(100);
            }
            SetFactoryTest(11, response, "不通过", "超时：未完成释放后连续按下", response,
                response.Length == 0 ? FailureClass.CommunicationTimeout : FailureClass.MeasurementOutOfRange, "");
        }

        private void TestGps(Dictionary<string, string> p)
        {
            int minSats, minCn, stableRequired;
            double maxHdop;
            ParseGpsThreshold(TestValue(6), out minSats, out minCn, out maxHdop, out stableRequired);
            var tracker = new GnssQualityTracker(minSats, minCn, maxHdop, stableRequired);
            DateTime deadline = DateTime.UtcNow.AddMilliseconds(TestTimeoutMs(6));
            string response = "";
            while (_serial.IsOpen && DateTime.UtcNow < deadline)
            {
                response = FactoryQuery("GNSSSTAT#", Math.Min(900, Math.Max(1, (int)(deadline - DateTime.UtcNow).TotalMilliseconds)));
                bool passed = tracker.Observe(response);
                SetFactoryTest(6, response, passed ? "通过" : "检测中", "定位/CN/HDOP 连续合格 " + tracker.Stable + "/" + stableRequired + "；天线电气开短路未测",
                    response, FailureClass.None, "");
                if (passed) return;
                Thread.Sleep(1000);
            }
            SetFactoryTest(6, response, "不通过", "未获得连续合格的新鲜定位/GSV质量", response,
                response.Length == 0 ? FailureClass.CommunicationTimeout : FailureClass.MeasurementOutOfRange, "");
        }

'''+s[b:]
# Remove the now unreachable voice transmission implementation.
a=s.index('        private void TestTts()');b=s.index('        private void RunSelectedTest()',a)
s=s[:a]+s[b:]
p.write_text(s,encoding='utf-8-sig')
p=root/'config/a300_tester.ini';s=p.read_text(encoding='utf-8').replace('expected_version=V1.281','expected_version=V3.054')
s+='\ntest_12_enabled=0\ntest_14_enabled=0\n';p.write_text(s,encoding='utf-8')
