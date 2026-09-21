using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace A300ProductionTester
{
    internal sealed class ResponseFramer
    {
        private readonly StringBuilder _buffer = new StringBuilder();
        private readonly int _capacity;

        public ResponseFramer(int capacity)
        {
            if (capacity < 16) throw new ArgumentOutOfRangeException("capacity");
            _capacity = capacity;
        }

        public IList<string> Push(string chunk)
        {
            List<string> lines = new List<string>();
            if (!string.IsNullOrEmpty(chunk)) _buffer.Append(chunk);
            int boundary;
            while ((boundary = IndexOfCrlf(_buffer)) >= 0)
            {
                lines.Add(_buffer.ToString(0, boundary));
                _buffer.Remove(0, boundary + 2);
            }
            if (_buffer.Length > _capacity)
                _buffer.Remove(0, _buffer.Length - _capacity);
            return lines;
        }

        public void Clear() { _buffer.Length = 0; }

        private static int IndexOfCrlf(StringBuilder text)
        {
            for (int i = 0; i + 1 < text.Length; i++)
                if (text[i] == '\r' && text[i + 1] == '\n') return i;
            return -1;
        }
    }

    internal sealed class ProductionReply
    {
        public string Command { get; private set; }
        public bool Success { get; private set; }
        public string ErrorCode { get; private set; }
        public IDictionary<string, string> Fields { get; private set; }
        public string Raw { get; private set; }

        public static string CommandKey(string command)
        {
            if (string.IsNullOrWhiteSpace(command)) return "";
            string value = command.Trim();
            int end = value.IndexOfAny(new[] { ',', '#', '\r', '\n' });
            if (end >= 0) value = value.Substring(0, end);
            return value.Trim().ToUpperInvariant();
        }

        public static bool IsCorrelatedComplete(string command, string line)
        {
            string expected = CommandKey(command);
            if (expected.Length == 0 || string.IsNullOrEmpty(line)) return false;
            if (expected == "PARAM")
                return line.StartsWith("PRO[", StringComparison.OrdinalIgnoreCase) &&
                       line.IndexOf("VER[", StringComparison.OrdinalIgnoreCase) >= 0 &&
                       line.IndexOf("ACC[", StringComparison.OrdinalIgnoreCase) >= 0;
            ProductionReply reply;
            return TryParse(line, expected, out reply);
        }

        public static bool TryParse(string line, string expectedCommand,
                                    out ProductionReply reply)
        {
            reply = null;
            if (string.IsNullOrWhiteSpace(line)) return false;
            string raw = line.TrimEnd('\r', '\n');
            string expected = CommandKey(expectedCommand);
            int separator = raw.IndexOfAny(new[] { ',', '=' });
            string actual = (separator < 0 ? raw : raw.Substring(0, separator)).Trim();
            if (!string.Equals(actual, expected, StringComparison.OrdinalIgnoreCase))
                return false;

            int successAt = raw.LastIndexOf("=Success!", StringComparison.OrdinalIgnoreCase);
            int failAt = raw.IndexOf("=Fail!", StringComparison.OrdinalIgnoreCase);
            if (successAt < 0 && failAt < 0) return false;
            bool success = successAt >= 0 && (failAt < 0 || successAt < failAt);
            int suffixAt = success ? successAt : failAt;
            string payload = raw.Substring(actual.Length, suffixAt - actual.Length);
            if (payload.StartsWith(",", StringComparison.Ordinal)) payload = payload.Substring(1);
            Dictionary<string, string> fields = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            if (payload.Length > 0)
            {
                foreach (string field in payload.Split(','))
                {
                    int equals = field.IndexOf('=');
                    if (equals > 0)
                        fields[field.Substring(0, equals).Trim()] = field.Substring(equals + 1).Trim();
                }
            }
            string error = "";
            if (!success)
            {
                error = raw.Substring(failAt + "=Fail!".Length).Trim();
                int space = error.IndexOfAny(new[] { ' ', ',', '\r', '\n' });
                if (space >= 0) error = error.Substring(0, space);
            }
            reply = new ProductionReply
            {
                Command = actual.ToUpperInvariant(),
                Success = success,
                ErrorCode = error,
                Fields = fields,
                Raw = raw,
            };
            return true;
        }
    }

    internal sealed class FactoryCapabilities
    {
        public int Version { get; private set; }
        public bool Acc { get; private set; }
        public bool Gsensor { get; private set; }
        public bool Voltage { get; private set; }
        public bool Relay { get; private set; }
        public bool Tts { get; private set; }
        public bool Rs485 { get; private set; }

        public static bool TryParse(string line, out FactoryCapabilities value)
        {
            value = null;
            ProductionReply reply;
            int version;
            if (!ProductionReply.TryParse(line, "FACTORYCAP", out reply) ||
                !reply.Success || !TryInt(reply, "VER", out version)) return false;
            value = new FactoryCapabilities
            {
                Version = version,
                Acc = IsOne(reply, "ACC"),
                Gsensor = IsOne(reply, "GSENSOR"),
                Voltage = IsOne(reply, "VOLTAGE"),
                Relay = IsOne(reply, "RELAY"),
                Tts = IsOne(reply, "TTS"),
                Rs485 = IsOne(reply, "RS485"),
            };
            return true;
        }

        private static bool IsOne(ProductionReply reply, string key)
        {
            int value;
            return TryInt(reply, key, out value) && value == 1;
        }

        private static bool TryInt(ProductionReply reply, string key, out int value)
        {
            string text;
            value = 0;
            return reply.Fields.TryGetValue(key, out text) &&
                   int.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out value);
        }
    }

    internal struct FactoryGsensor
    {
        public int X;
        public int Y;
        public int Z;
        public bool InterruptActive;
    }

    internal struct FactoryAcc
    {
        public bool Raw;
        public bool Debounced;
        public bool HardwarePriority;
        public bool LogicalOn;
    }

    internal struct FactoryVoltage
    {
        public int CarMillivolts;
        public int BatteryMillivolts;
        public bool Valid;
    }

    internal struct FactoryRelay
    {
        public bool ExternalLow;
        public bool McuAsserted;
        public bool PadAsserted;
        public int RemainingMilliseconds;
    }

    internal static class FactoryMeasurements
    {
        private static bool FieldInt(ProductionReply reply, string key, out int value)
        {
            string text;
            value = 0;
            return reply.Fields.TryGetValue(key, out text) &&
                   int.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out value);
        }

        public static bool TryParseGsensor(string line, out FactoryGsensor value)
        {
            value = new FactoryGsensor();
            ProductionReply reply;
            int x, y, z, interrupt;
            if (!ProductionReply.TryParse(line, "GSENSOR", out reply) || !reply.Success ||
                !FieldInt(reply, "X", out x) || !FieldInt(reply, "Y", out y) ||
                !FieldInt(reply, "Z", out z) || !FieldInt(reply, "INT", out interrupt)) return false;
            value = new FactoryGsensor { X = x, Y = y, Z = z, InterruptActive = interrupt != 0 };
            return true;
        }

        public static bool TryParseAcc(string line, out FactoryAcc value)
        {
            value = new FactoryAcc();
            ProductionReply reply;
            int raw, debounced, hardware, logical;
            if (!ProductionReply.TryParse(line, "ACCSTAT", out reply) || !reply.Success ||
                !FieldInt(reply, "RAW", out raw) || !FieldInt(reply, "DEB", out debounced) ||
                !FieldInt(reply, "HW", out hardware) || !FieldInt(reply, "LOGIC", out logical)) return false;
            value = new FactoryAcc { Raw = raw != 0, Debounced = debounced != 0,
                HardwarePriority = hardware != 0, LogicalOn = logical != 0 };
            return true;
        }

        public static bool TryParseVoltage(string line, out FactoryVoltage value)
        {
            value = new FactoryVoltage();
            ProductionReply reply;
            int car, battery, valid;
            if (!ProductionReply.TryParse(line, "STATUS", out reply) || !reply.Success ||
                !FieldInt(reply, "VCAR", out car) || !FieldInt(reply, "VBAT", out battery) ||
                !FieldInt(reply, "VALID", out valid)) return false;
            value = new FactoryVoltage { CarMillivolts = car, BatteryMillivolts = battery, Valid = valid == 1 };
            return true;
        }

        public static bool TryParseRelay(string line, out FactoryRelay value)
        {
            value = new FactoryRelay();
            ProductionReply reply;
            int mcu, pad, remaining = 0;
            string output;
            if (!ProductionReply.TryParse(line, "RELAYTEST", out reply) || !reply.Success ||
                !reply.Fields.TryGetValue("OUT", out output) ||
                !FieldInt(reply, "MCU", out mcu) || !FieldInt(reply, "PAD", out pad)) return false;
            FieldInt(reply, "REMAIN_MS", out remaining);
            value = new FactoryRelay { ExternalLow = output == "LOW", McuAsserted = mcu != 0,
                PadAsserted = pad != 0, RemainingMilliseconds = remaining };
            return output == "LOW" || output == "HIGH";
        }

        public static bool VoltageInRange(int millivolts, decimal minimumVolts,
                                          decimal maximumVolts)
        {
            decimal value = millivolts / 1000m;
            return value >= minimumVolts && value <= maximumVolts;
        }
    }

    internal sealed class GsensorMovementTracker
    {
        private readonly int _threshold;
        private bool _baseline;
        private int _x;
        private int _y;
        private int _z;
        public int SampleCount { get; private set; }
        public int MaxDelta { get; private set; }

        public GsensorMovementTracker(int threshold) { _threshold = threshold; }

        public bool Add(int x, int y, int z)
        {
            SampleCount++;
            if (!_baseline)
            {
                _baseline = true;
                _x = x; _y = y; _z = z;
                return false;
            }
            long delta = Math.Abs((long)x - _x) + Math.Abs((long)y - _y) + Math.Abs((long)z - _z);
            if (delta > int.MaxValue) delta = int.MaxValue;
            if ((int)delta > MaxDelta) MaxDelta = (int)delta;
            return SampleCount >= 2 && MaxDelta >= _threshold;
        }
    }

    internal sealed class AccTransitionTracker
    {
        private readonly int _required;
        private bool _hasState;
        private bool _state;
        public int OnCount { get; private set; }
        public int OffCount { get; private set; }

        public AccTransitionTracker(int required) { _required = required; }

        public bool Add(bool state)
        {
            if (!_hasState) { _hasState = true; _state = state; return false; }
            if (state == _state) return OnCount >= _required && OffCount >= _required;
            _state = state;
            if (state) OnCount++; else OffCount++;
            return OnCount >= _required && OffCount >= _required;
        }
    }

    internal static class SemanticFirmwareVersion
    {
        private static readonly Regex VersionToken = new Regex(@"V\d+\.\d+", RegexOptions.IgnoreCase);

        public static bool TryExtract(string fullVersion, out string semantic)
        {
            semantic = "";
            if (string.IsNullOrEmpty(fullVersion)) return false;
            MatchCollection matches = VersionToken.Matches(fullVersion);
            if (matches.Count == 0) return false;
            semantic = "V" + matches[matches.Count - 1].Value.Substring(1);
            return true;
        }

        public static bool Matches(string fullVersion, string expected)
        {
            string actual;
            return TryExtract(fullVersion, out actual) &&
                   string.Equals(actual, expected, StringComparison.OrdinalIgnoreCase);
        }
    }

    internal static class GbkTtsValidator
    {
        private static Encoding StrictGbk()
        {
            return Encoding.GetEncoding(936, EncoderFallback.ExceptionFallback,
                                        DecoderFallback.ExceptionFallback);
        }

        public static bool Validate(string text, out byte[] encoded, out string error)
        {
            encoded = new byte[0];
            error = "INVALID_TEXT";
            if (string.IsNullOrEmpty(text) || text.IndexOfAny(new[] { ',', '#', '\r', '\n', '\0' }) >= 0)
                return false;
            try { encoded = StrictGbk().GetBytes(text); }
            catch (EncoderFallbackException) { return false; }
            return encoded.Length >= 1 && encoded.Length <= 160;
        }

        public static bool BuildWireCommand(string text, out byte[] command, out string error)
        {
            byte[] payload;
            command = new byte[0];
            if (!Validate(text, out payload, out error)) return false;
            byte[] prefix = Encoding.ASCII.GetBytes("TTS,");
            byte[] suffix = Encoding.ASCII.GetBytes("#\r\n");
            command = new byte[prefix.Length + payload.Length + suffix.Length];
            Buffer.BlockCopy(prefix, 0, command, 0, prefix.Length);
            Buffer.BlockCopy(payload, 0, command, prefix.Length, payload.Length);
            Buffer.BlockCopy(suffix, 0, command, prefix.Length + payload.Length, suffix.Length);
            error = "";
            return true;
        }
    }

    internal enum FailureClass
    {
        None,
        CommunicationTimeout,
        UnsupportedByFirmware,
        FirmwareDriverFailure,
        MeasurementOutOfRange,
        PendingOperatorConfirmation,
        HardwareFailure,
        SkippedNotTested,
    }

    internal static class TestClassification
    {
        public static FailureClass FromTimeout() { return FailureClass.CommunicationTimeout; }
        public static FailureClass FromCapability(bool supported)
        { return supported ? FailureClass.None : FailureClass.UnsupportedByFirmware; }
        public static FailureClass FromOperator(bool accepted)
        { return accepted ? FailureClass.None : FailureClass.HardwareFailure; }
        public static FailureClass Rs485Excluded() { return FailureClass.SkippedNotTested; }
    }

    internal static class RelayWorkflow
    {
        public const string RequiredFinalCommand = "RELAYTEST,HIGH#";
        public static IList<string> AmbiguousTimeoutRecovery()
        {
            return new[] { "RELAYTEST,STATUS#", RequiredFinalCommand };
        }
    }
}
