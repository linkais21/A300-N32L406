# Build script - A300-first
$ErrorActionPreference = "Stop"

cd D:\A700open\A300\A300-first
$env:Path = "D:\SofWare\STM32CubeIDE_2.1.1\STM32CubeIDE\plugins\com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32.14.3.rel1.win32_1.0.100.202602081740\tools\bin;$env:Path"

$SDK = "sdk/Nations.N32L40x_Library.2.2.0/firmware"

# Auto-generate build_version.h with current timestamp
$now        = Get-Date
$buildNum   = $now.ToString("yyyyMMdd_HHmmss")
$buildDate  = $now.ToString("yyyy-MM-dd HH:mm:ss")
$fullVer    = "T663B_B409_$buildNum"

@"
#ifndef BUILD_VERSION_H
#define BUILD_VERSION_H

#define FW_BUILD_NUMBER  "$buildNum"
#define FW_BUILD_DATE    "$buildDate"
#define FW_FULL_VERSION  "$fullVer"

#endif /* BUILD_VERSION_H */
"@ | Out-File -FilePath "include\build_version.h" -Encoding utf8

Write-Host "Version: $fullVer"

$CFLAGS = "-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard -O2 -g3 -Wall -Wextra -ffunction-sections -fdata-sections -Iinclude -I$SDK/CMSIS/core -I$SDK/CMSIS/device -I$SDK/n32l40x_std_periph_driver/inc -DUSE_STDPERIPH_DRIVER -DN32L40X -DSYSCLK_SRC=3 -DSYSCLK_FREQ=64000000 -std=c99"

$sources = @(
    "src/main.c",
    "src/hw_init.c",
    "src/ec800m.c",
    "src/debug_uart.c",
    "src/syscalls.c",
    "src/gps.c",
    "src/jt808.c",
    "src/jt808_params.c",
    "src/at_config.c",
    "src/adc_monitor.c",
    "src/spi_flash.c",
    "src/i2c_accel.c",
    "src/relay.c",
    "src/flash_config.c",
    "src/fota.c",
    "src/geofence.c",
    "src/mileage.c",
    "src/peripherals.c",
    "src/power_mgr.c",
    "src/tcp_manager.c",
    "src/startup_n32l40x.s",
    "$SDK/CMSIS/device/system_n32l40x.c",
    "$SDK/n32l40x_std_periph_driver/src/n32l40x_gpio.c",
    "$SDK/n32l40x_std_periph_driver/src/n32l40x_rcc.c",
    "$SDK/n32l40x_std_periph_driver/src/n32l40x_usart.c",
    "$SDK/n32l40x_std_periph_driver/src/n32l40x_adc.c",
    "$SDK/n32l40x_std_periph_driver/src/n32l40x_dma.c",
    "$SDK/n32l40x_std_periph_driver/src/n32l40x_spi.c",
    "$SDK/n32l40x_std_periph_driver/src/n32l40x_i2c.c",
    "$SDK/n32l40x_std_periph_driver/src/n32l40x_tim.c",
    "$SDK/n32l40x_std_periph_driver/src/n32l40x_iwdg.c",
    "$SDK/n32l40x_std_periph_driver/src/n32l40x_pwr.c",
    "$SDK/n32l40x_std_periph_driver/src/n32l40x_rtc.c",
    "$SDK/n32l40x_std_periph_driver/src/n32l40x_exti.c",
    "$SDK/n32l40x_std_periph_driver/src/misc.c"
)

foreach ($src in $sources) {
    $obj = "build\" + $src.Replace("/", "\").Replace(".c", ".o").Replace(".s", ".o")
    $objDir = Split-Path $obj -Parent

    if (-not (Test-Path $objDir)) {
        New-Item -ItemType Directory -Path $objDir -Force | Out-Null
    }

    # Rebuild every object to avoid stale or mixed-flag objects in firmware.
    $forceRebuild = $true

    if ($forceRebuild -or -not (Test-Path $obj)) {
        Write-Host "Compiling $src..."
        if ($src -like "*.s") {
            $cmdArgs = "-mcpu=cortex-m4", "-mthumb", "-mfpu=fpv4-sp-d16", "-mfloat-abi=hard", "-g3", "-c", $src, "-o", $obj
            & arm-none-eabi-gcc.exe $cmdArgs
        } else {
            $cmdArgs = $CFLAGS.Split() + @("-c", $src, "-o", $obj)
            & arm-none-eabi-gcc.exe $cmdArgs
        }
        if ($LASTEXITCODE -ne 0) {
            throw "Compile $src failed"
        }
    }
}

Write-Host "All sources compiled"

# Link ELF
Write-Host "Linking firmware..."
$objs = Get-ChildItem -Recurse build/*.o | ForEach-Object { $_.FullName }
$LDFLAGS = "-mcpu=cortex-m4", "-mthumb", "-mfpu=fpv4-sp-d16", "-mfloat-abi=hard",
           "-Tldscript/n32l406.ld", "-Wl,--gc-sections",
           "-Wl,-Map=build/a300_firmware.map", "-lc", "-lm"
$allArgs = $LDFLAGS + $objs + @("-o", "build/a300_firmware.elf")
& arm-none-eabi-gcc.exe $allArgs
if ($LASTEXITCODE -ne 0) { throw "Link failed" }

# Generate HEX
Write-Host "Generating HEX..."
& arm-none-eabi-objcopy.exe -O ihex build/a300_firmware.elf build/a300_firmware.hex
Write-Host "Build SUCCESS! [$buildDate]" -ForegroundColor Green
& arm-none-eabi-size.exe build/a300_firmware.elf
