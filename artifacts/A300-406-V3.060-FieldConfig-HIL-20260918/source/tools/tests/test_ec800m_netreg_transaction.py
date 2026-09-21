import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]


def find_compiler() -> str:
    compiler = os.environ.get("CC") or shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
    if compiler:
        return compiler
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        for executable in ("gcc.exe", "clang.exe", "cc.exe"):
            candidate = Path(directory.strip('"')) / executable
            if candidate.is_file():
                return str(candidate)
        if "WinLibs" in directory and directory.rstrip("\\/").lower().endswith("bin"):
            return str(Path(directory.strip('"')) / "gcc.exe")
    matches = list(Path.home().glob("scoop/apps/gcc/current/bin/gcc.exe"))
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        matches += list(Path(local_app_data).glob("Microsoft/WinGet/Packages/BrechtSanders.WinLibs*/mingw64/bin/gcc.exe"))
        matches += list(Path(local_app_data).glob("Microsoft/WinGet/Packages/*WinLibs*/mingw64/bin/gcc.exe"))
    if matches:
        return str(matches[0])
    raise AssertionError("host C compiler is required for EC800M response tests")


HARNESS = r'''
#include <assert.h>
#include <stddef.h>
#include <string.h>

#include "ec800m_at_response.h"

static ec800m_at_end_t response_end(const char *text)
{
    return ec800m_at_response_end(text, (uint16_t)strlen(text));
}

int main(void)
{
    int status = -1;
    unsigned int candidate;
    char response[] = "\r\n+CEREG: 0,0\r\nOK\r\n";
    const uint8_t *payload = NULL;
    uint16_t payload_length = 0U;
    ec800m_qird_diag_t qird_diag;
    static const uint8_t qird_response[] = {
        '\r','\n','+','Q','I','R','D',':',' ','5','\r','\n',
        0x7e,0x00,0x0d,0x0a,0x7e,
        '\r','\n','O','K','\r','\n'
    };
    static const uint8_t qird_no_leading_crlf[] = {
        '+','Q','I','R','D',':',' ','1','\r','\n',0x7e,
        '\r','\n','O','K','\r','\n'
    };
    static const uint8_t qird_with_echo[] = {
        'A','T','+','Q','I','R','D','=','0',',','1','2','0','0','\r','\n',
        '+','Q','I','R','D',':',' ','1','\r','\n',0x7e,
        '\r','\n','O','K','\r','\n'
    };
    static const uint8_t qird_with_blank_line_before_ok[] = {
        '\r','\n','+','Q','I','R','D',':',' ','2','2','\r','\n',
        0x7e,0x81,0x00,0x00,0x0d,0x00,0x01,0x01,0x23,0x45,0x67,
        0x89,0x01,0x23,0x00,0x01,0x00,0x00,0x00,0x00,0x00,0x7e,
        '\r','\n','\r','\n','O','K','\r','\n'
    };

    assert(response_end("\r\n+CEREG:") == EC800M_AT_PENDING);
    assert(response_end("\r\n+CEREG: 0,2\r\nO") == EC800M_AT_PENDING);
    assert(response_end("\r\n+CEREG: 0,2\r\nOK\r\n") == EC800M_AT_OK);
    assert(response_end("\r\nERROR\r\n") == EC800M_AT_ERROR);
    assert(response_end("\r\nOKAY\r\n") == EC800M_AT_PENDING);
    assert(response_end("prefix OK suffix") == EC800M_AT_PENDING);

    for (candidate = 0U; candidate <= 5U; ++candidate) {
        response[12] = (char)('0' + candidate);
        status = -1;
        assert(ec800m_parse_reg_status(response, "+CEREG:", &status));
        assert(status == (int)candidate);
    }

    status = -1;
    assert(ec800m_parse_reg_status("\r\n+CGREG: 0,5\r\nOK\r\n", "+CGREG:", &status));
    assert(status == 5);
    assert(!ec800m_parse_reg_status("\r\n+CEREG:\r\nOK\r\n", "+CEREG:", &status));
    assert(!ec800m_parse_reg_status("\r\n+CEREG: 0,6\r\nOK\r\n", "+CEREG:", &status));
    assert(!ec800m_parse_reg_status("\r\n+CEREG: 0,2", "+CEREG:", &status));
    assert(!ec800m_parse_reg_status("\r\n+CEREG: 0,2\r\nOK\r\n", "+CGREG:", &status));

    assert(ec800m_parse_qird_response(qird_response, sizeof qird_response,
                                      &payload, &payload_length));
    assert(payload_length == 5U);
    assert(payload == &qird_response[12]);
    assert(payload[1] == 0x00U && payload[2] == 0x0dU && payload[3] == 0x0aU);
    assert(!ec800m_parse_qird_response(qird_response, sizeof qird_response - 3U,
                                       &payload, &payload_length));
    assert(ec800m_parse_qird_response(qird_no_leading_crlf,
                                      sizeof qird_no_leading_crlf,
                                      &payload, &payload_length));
    assert(payload == &qird_no_leading_crlf[10] && payload_length == 1U);
    assert(ec800m_parse_qird_response(qird_with_echo, sizeof qird_with_echo,
                                      &payload, &payload_length));
    assert(payload == &qird_with_echo[26] && payload_length == 1U);
    assert(ec800m_parse_qird_response(qird_with_blank_line_before_ok,
                                      sizeof qird_with_blank_line_before_ok,
                                      &payload, &payload_length));
    assert(payload == &qird_with_blank_line_before_ok[13]);
    assert(payload_length == 22U);
    assert(!ec800m_parse_qird_response_diag(qird_response,
                                            sizeof qird_response - 3U,
                                            &payload, &payload_length,
                                            &qird_diag));
    assert(qird_diag.stage == EC800M_QIRD_STAGE_TAIL);
    assert(qird_diag.total_length == sizeof qird_response - 3U);
    assert(qird_diag.header_offset == 2);
    assert(qird_diag.declared_length == 5U);
    assert(qird_diag.remaining_length == 3U);
    assert(qird_diag.tail_mask == 0x07U);

    return 0;
}
'''


def main() -> None:
    compiler = find_compiler()
    with tempfile.TemporaryDirectory(prefix="ec800m_netreg_") as directory:
        temp = Path(directory)
        harness = temp / "harness.c"
        executable = temp / "ec800m_netreg.exe"
        harness.write_text(HARNESS, encoding="utf-8")
        command = [
            compiler,
            "-std=c99",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(ROOT / "include"),
            str(harness),
            str(ROOT / "src" / "ec800m_at_response.c"),
            "-o",
            str(executable),
        ]
        built = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if built.returncode != 0:
            raise AssertionError(f"host build failed:\n{built.stdout}{built.stderr}")
        executed = subprocess.run([str(executable)], cwd=ROOT, capture_output=True, text=True)
        if executed.returncode != 0:
            raise AssertionError(f"host harness failed:\n{executed.stdout}{executed.stderr}")

    print("EC800M network-registration transaction: PASS")


if __name__ == "__main__":
    main()
