from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).parents[2]


def test_fota_check_parser_contract():
    """Compile and run the bounded C99 update-check parser contract."""
    cc = shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
    if not cc:
        raise AssertionError("a C compiler is required for fota_check_parser host tests")

    source = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>

#include "fota_check_parser.h"

#define JSON_LENGTH(value) ((uint16_t)(sizeof(value) - 1U))

static void expect_valid(const char *json, uint16_t length, int available,
                         uint32_t version, uint32_t size, const char *url,
                         uint32_t key_id, const char *token)
{
    fota_check_response_t response;
    assert(fota_check_parse(json, length, &response));
    assert(response.update_available == (available != 0));
    assert(response.version_code == version);
    assert(response.size == size);
    assert(strcmp(response.download_url, url) == 0);
    assert(response.signing_key_id == key_id);
    assert(strcmp(response.download_token, token) == 0);
    if (available) {
        assert(response.package_sha256[0] == 0x00);
        assert(response.package_sha256[31] == 0x1f);
        assert(response.signature[0] == 0x20);
        assert(response.signature[63] == 0x5f);
    }
}

static void expect_invalid(const char *json, uint16_t length)
{
    fota_check_response_t response;
    fota_check_response_t original;
    memset(&response, 0xA5, sizeof response);
    memcpy(&original, &response, sizeof response);
    assert(!fota_check_parse(json, length, &response));
    assert(memcmp(&response, &original, sizeof response) == 0);
}

int main(void)
{
    char assembled[512];
    const char *fragment_a = "{\"downloadUrl\":\"http://fota.lhhn.net/firmware.bin\",\"size\":4096,\"sha256\":\"000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f\",\"sig";
    const char *fragment_b = "nature\":\"202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f404142434445464748494a4b4c4d4e4f505152535455565758595a5b5c5d5e5f\",\"signingKeyId\":1,\"downloadToken\":\"task-token-123\",\"updateAvailable\":true,\"versionCode\":3002}";
    const char *overflow_prefix = "{\"updateAvailable\":true,\"versionCode\":1,\"size\":1,\"downloadUrl\":\"";
    char overflow_json[256];
    size_t first_length = strlen(fragment_a);
    size_t second_length = strlen(fragment_b);
    size_t overflow_prefix_length = strlen(overflow_prefix);

    /* HTTP assembly belongs to the caller; the parser accepts only the final slice. */
    memcpy(assembled, fragment_a, first_length);
    memcpy(assembled + first_length, fragment_b, second_length);
    expect_valid(assembled, (uint16_t)(first_length + second_length), 1, 3002U,
                 4096U, "http://fota.lhhn.net/firmware.bin", 1U, "task-token-123");

    expect_valid(" \r\n { \"updateAvailable\" : false } \t",
                 JSON_LENGTH(" \r\n { \"updateAvailable\" : false } \t"),
                 0, 0U, 0U, "", 0U, "");

    expect_invalid("{\"updateAvailable\":true}",
                   JSON_LENGTH("{\"updateAvailable\":true}"));
    expect_invalid("{\"updateAvailable\":true,\"versionCode\":1,\"size\":1,\"downloadUrl\":\"u\",\"sha256\":\"000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f\",\"signature\":\"202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f404142434445464748494a4b4c4d4e4f505152535455565758595a5b5c5d5e5f\",\"signingKeyId\":1}",
                   JSON_LENGTH("{\"updateAvailable\":true,\"versionCode\":1,\"size\":1,\"downloadUrl\":\"u\",\"sha256\":\"000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f\",\"signature\":\"202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f404142434445464748494a4b4c4d4e4f505152535455565758595a5b5c5d5e5f\",\"signingKeyId\":1}"));
    expect_invalid("{\"updateAvailable\":true,\"versionCode\":1,\"size\":1,\"downloadUrl\":\"u\",\"sha256\":\"000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f\",\"signature\":\"202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f404142434445464748494a4b4c4d4e4f505152535455565758595a5b5c5d5e5f\",\"signingKeyId\":1,\"downloadToken\":\"\"}",
                   JSON_LENGTH("{\"updateAvailable\":true,\"versionCode\":1,\"size\":1,\"downloadUrl\":\"u\",\"sha256\":\"000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f\",\"signature\":\"202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f404142434445464748494a4b4c4d4e4f505152535455565758595a5b5c5d5e5f\",\"signingKeyId\":1,\"downloadToken\":\"\"}"));
    expect_invalid("{\"updateAvailable\":false,\"size\":1}",
                   JSON_LENGTH("{\"updateAvailable\":false,\"size\":1}"));
    expect_invalid("{\"updateAvailable\":true,\"versionCode\":1,\"versionCode\":2,\"size\":1,\"downloadUrl\":\"u\"}",
                   JSON_LENGTH("{\"updateAvailable\":true,\"versionCode\":1,\"versionCode\":2,\"size\":1,\"downloadUrl\":\"u\"}"));
    expect_invalid("{\"updateAvailable\":1}",
                   JSON_LENGTH("{\"updateAvailable\":1}"));
    expect_invalid("{\"updateAvailable\":true,\"versionCode\":\"1\",\"size\":1,\"downloadUrl\":\"u\"}",
                   JSON_LENGTH("{\"updateAvailable\":true,\"versionCode\":\"1\",\"size\":1,\"downloadUrl\":\"u\"}"));
    expect_invalid("{\"updateAvailable\":true,\"versionCode\":1,\"size\":true,\"downloadUrl\":\"u\"}",
                   JSON_LENGTH("{\"updateAvailable\":true,\"versionCode\":1,\"size\":true,\"downloadUrl\":\"u\"}"));
    expect_invalid("{\"updateAvailable\":true,\"versionCode\":1,\"size\":1,\"downloadUrl\":1}",
                   JSON_LENGTH("{\"updateAvailable\":true,\"versionCode\":1,\"size\":1,\"downloadUrl\":1}"));
    expect_invalid("{\"updateAvailable\":true,\"versionCode\":-1,\"size\":1,\"downloadUrl\":\"u\"}",
                   JSON_LENGTH("{\"updateAvailable\":true,\"versionCode\":-1,\"size\":1,\"downloadUrl\":\"u\"}"));
    expect_invalid("{\"updateAvailable\":true,\"versionCode\":01,\"size\":1,\"downloadUrl\":\"u\"}",
                   JSON_LENGTH("{\"updateAvailable\":true,\"versionCode\":01,\"size\":1,\"downloadUrl\":\"u\"}"));
    expect_invalid("{\"updateAvailable\":true,\"versionCode\":4294967296,\"size\":1,\"downloadUrl\":\"u\"}",
                   JSON_LENGTH("{\"updateAvailable\":true,\"versionCode\":4294967296,\"size\":1,\"downloadUrl\":\"u\"}"));
    expect_invalid("{\"updateAvailable\":true,\"versionCode\":1,\"size\":1,\"downloadUrl\":\"http:\\\\/\\\\/host\"}",
                   JSON_LENGTH("{\"updateAvailable\":true,\"versionCode\":1,\"size\":1,\"downloadUrl\":\"http:\\\\/\\\\/host\"}"));
    expect_valid("{\"updateAvailable\":true,\"versionCode\":3002,\"size\":4096,\"downloadUrl\":\"http://fota.lhhn.net/firmware.bin\",\"sha256\":\"000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f\",\"signature\":\"202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f404142434445464748494a4b4c4d4e4f505152535455565758595a5b5c5d5e5f\",\"signingKeyId\":1,\"downloadToken\":\"task-token-123\",\"tokenExpiresAt\":\"2026-09-12T03:20:00Z\"}",
                 JSON_LENGTH("{\"updateAvailable\":true,\"versionCode\":3002,\"size\":4096,\"downloadUrl\":\"http://fota.lhhn.net/firmware.bin\",\"sha256\":\"000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f\",\"signature\":\"202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f404142434445464748494a4b4c4d4e4f505152535455565758595a5b5c5d5e5f\",\"signingKeyId\":1,\"downloadToken\":\"task-token-123\",\"tokenExpiresAt\":\"2026-09-12T03:20:00Z\"}"),
                 1, 3002U, 4096U, "http://fota.lhhn.net/firmware.bin",
                 1U, "task-token-123");
    expect_invalid("{\"updateAvailable\":false}x",
                   JSON_LENGTH("{\"updateAvailable\":false}x"));
    expect_invalid("{\"updateAvailable\":false",
                   JSON_LENGTH("{\"updateAvailable\":false"));
    expect_invalid("{\"updateAvailable\":false}\0ignored",
                   JSON_LENGTH("{\"updateAvailable\":false}\0ignored"));

    memcpy(overflow_json, overflow_prefix, overflow_prefix_length);
    memset(overflow_json + overflow_prefix_length, 'a', 128U);
    overflow_json[overflow_prefix_length + 128U] = '"';
    overflow_json[overflow_prefix_length + 129U] = '}';
    expect_invalid(overflow_json, (uint16_t)(overflow_prefix_length + 130U));

    expect_invalid(0, 0U);
    assert(!fota_check_parse("{\"updateAvailable\":false}",
                             JSON_LENGTH("{\"updateAvailable\":false}"), NULL));
    return 0;
}
'''

    with tempfile.TemporaryDirectory() as td:
        temp_dir = Path(td)
        harness = temp_dir / "fota_check_parser_host.c"
        executable = temp_dir / "fota_check_parser_host.exe"
        harness.write_text(source, encoding="ascii")
        subprocess.run(
            [
                cc,
                "-std=c99",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I",
                str(ROOT / "include"),
                str(harness),
                str(ROOT / "src" / "fota_check_parser.c"),
                "-o",
                str(executable),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run([str(executable)], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    test_fota_check_parser_contract()
    print("test_fota_check_parser: PASS")
