$ErrorActionPreference = "Stop"
Set-Location "D:\A700open\A300\A300-first"
$env:Path = "D:\SofWare\STM32CubeIDE_2.1.1\STM32CubeIDE\plugins\com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32.14.3.rel1.win32_1.0.100.202602081740\tools\bin;$env:Path"

# Generate version header
Write-Host "=== Generating build version ===" -ForegroundColor Cyan
& powershell.exe -ExecutionPolicy Bypass -File "gen_version.ps1"

Write-Host "`n=== Recompiling main.c with new version ===" -ForegroundColor Cyan
$SDK = "sdk/Nations.N32L40x_Library.2.2.0/firmware"
$CFLAGS = "-mcpu=cortex-m4", "-mthumb", "-mfpu=fpv4-sp-d16", "-mfloat-abi=hard",
          "-O2", "-g3", "-Wall", "-ffunction-sections", "-fdata-sections",
          "-Iinclude", "-I$SDK/CMSIS/core", "-I$SDK/CMSIS/device",
          "-I$SDK/n32l40x_std_periph_driver/inc",
          "-DUSE_STDPERIPH_DRIVER", "-DN32L40X", "-DSYSCLK_SRC=3",
          "-DSYSCLK_FREQ=64000000", "-std=c99"

# Recompile main.c to pick up new version
& arm-none-eabi-gcc.exe $CFLAGS -c src/main.c -o build/src/main.o
if ($LASTEXITCODE -ne 0) { throw "Compile main.c failed" }

Write-Host "`n=== Linking firmware with updated hw_init.o + main.o ===" -ForegroundColor Cyan

$objs = Get-ChildItem -Recurse build/*.o | Where-Object {
    $_.FullName -notlike "*test*" -and
    $_.FullName -notlike "*dbg_*"
} | ForEach-Object { $_.FullName }

$LDFLAGS = "-mcpu=cortex-m4", "-mthumb", "-mfpu=fpv4-sp-d16", "-mfloat-abi=hard",
           "-Tldscript/n32l406.ld", "-Wl,--gc-sections",
           "-Wl,-Map=build/a300_firmware.map", "-lc", "-lm"

$allArgs = $LDFLAGS + $objs + @("-o", "build/a300_firmware.elf")

& arm-none-eabi-gcc.exe $allArgs

if ($LASTEXITCODE -ne 0) { throw "Link failed" }

Write-Host "Creating HEX..." -ForegroundColor Yellow
& arm-none-eabi-objcopy.exe -O ihex build/a300_firmware.elf build/a300_firmware.hex

Write-Host "`nBuild SUCCESS!" -ForegroundColor Green
& arm-none-eabi-size.exe build/a300_firmware.elf

Write-Host "`nFirmware: build/a300_firmware.hex" -ForegroundColor Cyan
Write-Host "JTAG disabled, PA15 now works as GPIO for EC800M power enable"
