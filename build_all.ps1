# Build script - A300-first
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $repoRoot
$localToolchainDir = Join-Path $repoRoot ".toolchain\bin"
$vendorToolchainDir = [string]::Concat("D:\A300_Tools\A300-N32G452\", [char]0x5DE5, [char]0x5177, [char]0x94FE, "\arm-gnu-toolchain-14.3.rel1\bin")
$toolchainCandidates = @(
    $env:A300_ARM_TOOLCHAIN,
    $localToolchainDir,
    $vendorToolchainDir,
    "D:\ST\STM32CubeIDE_2.1.1\STM32CubeIDE\plugins\com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32.14.3.rel1.win32_1.0.100.202602081740\tools\bin"
)
$toolchainBin = $toolchainCandidates | Where-Object {
    $_ -and (Test-Path -LiteralPath (Join-Path $_ "arm-none-eabi-gcc.exe"))
} | Select-Object -First 1
if (-not $toolchainBin) { throw "ARM GCC toolchain not found" }
$mappedToolchainDrive = $null
# GCC's Windows runtime can mis-handle non-ASCII install paths while locating
# its sibling libgcc/newlib directories.  Give it an ASCII drive alias for the
# duration of this build so the default Chinese toolchain path remains usable.
if ($toolchainBin -match '[^\x00-\x7F]') {
    $mapDrive = if ($env:A300_TOOLCHAIN_DRIVE) { $env:A300_TOOLCHAIN_DRIVE } else { "T:" }
    if ($mapDrive -notmatch '^[A-Za-z]:$') { throw "A300_TOOLCHAIN_DRIVE must be a drive letter such as T:" }
    $toolchainRoot = Split-Path -Parent $toolchainBin
    $existingMapRaw = (& subst.exe $mapDrive 2>$null | Out-String).Trim()
    # `subst X:` prints a localized error when X is unused; only a mapping
    # record (which contains `=>`) should be treated as an existing mapping.
    $existingMap = if ($existingMapRaw -match '=>') { $existingMapRaw } else { "" }
    if ($existingMap) {
        if ($existingMap -notmatch [regex]::Escape($toolchainRoot)) {
            throw "$mapDrive is already mapped to another directory; set A300_TOOLCHAIN_DRIVE to a free drive"
        }
    } else {
        & subst.exe $mapDrive $toolchainRoot | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Failed to map $toolchainRoot to $mapDrive" }
        $mappedToolchainDrive = $mapDrive
    }
    $toolchainBin = Join-Path $mapDrive (Split-Path -Leaf $toolchainBin)
}
$env:Path = "$toolchainBin;$env:Path"
Write-Host "ARM toolchain: $toolchainBin"
$gcc = Join-Path $toolchainBin "arm-none-eabi-gcc.exe"
$objcopy = Join-Path $toolchainBin "arm-none-eabi-objcopy.exe"
$size = Join-Path $toolchainBin "arm-none-eabi-size.exe"

if (Test-Path -LiteralPath (Join-Path $repoRoot "build")) {
    Remove-Item -LiteralPath (Join-Path $repoRoot "build") -Recurse -Force
}

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

$CFLAGS = "-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard -Os -g0 -Wall -Wextra -flto=1 -flto-partition=one -ffunction-sections -fdata-sections -Iinclude -Ithird_party/micro-ecc -I$SDK/CMSIS/core -I$SDK/CMSIS/device -I$SDK/n32l40x_std_periph_driver/inc -DUSE_STDPERIPH_DRIVER -DN32L40X -DSYSCLK_SRC=3 -DSYSCLK_FREQ=64000000 -DuECC_SUPPORTS_secp160r1=0 -DuECC_SUPPORTS_secp192r1=0 -DuECC_SUPPORTS_secp224r1=0 -DuECC_SUPPORTS_secp256k1=0 -DuECC_SUPPORTS_secp256r1=1 -DuECC_SUPPORT_COMPRESSED_POINT=0 -DuECC_PLATFORM=uECC_arch_other -std=c99"

$sources = @(
    "src/main.c",
    "src/hw_init.c",
    "src/ec800m.c",
    "src/debug_uart.c",
    "src/syscalls.c",
    "src/ram_watermark.c",
    "src/ec800m_at_response.c",
    "src/gps.c",
    "src/jt808.c",
    "src/jt808_params.c",
    "src/jt808_session.c",
    "src/terminal_identity.c",
    "src/at_config.c",
    "src/adc_monitor.c",
    "src/spi_flash.c",
    "src/ext_flash_store.c",
    "src/blind_zone.c",
    "src/blind_zone_replay.c",
    "src/firmware_signature.c",
    "src/reset_diag.c",
    "src/i2c_accel.c",
    "src/relay.c",
    "src/flash_config.c",
    "src/fota.c",
    "src/agnss_manager.c",
    "src/agnss_huada.c",
    "src/agnss_zhongkewei.c",
    "src/geofence.c",
    "src/mileage.c",
    "src/peripherals.c",
    "src/sms_command.c",
    "src/f39_command.c",
    "src/f39_config_adapter.c",
    "src/f39_reply.c",
    "src/sms_ingress.c",
    "src/power_mgr.c",
    "src/work_mode.c",
    "src/work_mode_sleep.c",
    "src/tcp_manager.c",
    "src/agnss_storage.c",
    "third_party/micro-ecc/uECC.c",
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
            $cmdArgs = "-mcpu=cortex-m4", "-mthumb", "-mfpu=fpv4-sp-d16", "-mfloat-abi=hard", "-g0", "-c", $src, "-o", $obj
            & $gcc $cmdArgs
        } else {
            $compileFlags = $CFLAGS.Split()
            if ($src -eq "src/firmware_signature.c" -or $src -eq "third_party/micro-ecc/uECC.c") {
                $compileFlags += "-fno-lto"
            }
            $cmdArgs = $compileFlags + @("-c", $src, "-o", $obj)
            & $gcc $cmdArgs
        }
        if ($LASTEXITCODE -ne 0) {
            throw "Compile $src failed"
        }
    }
}

Write-Host "All sources compiled"

# Link ELF
Write-Host "Linking firmware..."
$objs = foreach ($src in $sources) {
    $obj = "build\" + $src.Replace("/", "\").Replace(".c", ".o").Replace(".s", ".o")
    (Resolve-Path -LiteralPath $obj).Path
}
$LDFLAGS = "-mcpu=cortex-m4", "-mthumb", "-mfpu=fpv4-sp-d16", "-mfloat-abi=hard",
           "-Os", "-g0",
           "-Tldscript/n32l406.ld", "-Wl,--gc-sections",
           "-Wl,-Map=build/a300_firmware.map", "-flto=1", "-flto-partition=one",
           "--specs=nano.specs", "-lc", "-lgcc", "-lm"
$allArgs = $LDFLAGS + $objs + @("-o", "build/a300_firmware.elf")
& $gcc $allArgs
if ($LASTEXITCODE -ne 0) { throw "Link failed" }

# Generate HEX
Write-Host "Generating HEX..."
& $objcopy -O ihex build/a300_firmware.elf build/a300_firmware.hex
Write-Host "Build SUCCESS! [$buildDate]" -ForegroundColor Green
& $size build/a300_firmware.elf
if ($mappedToolchainDrive) {
    & subst.exe $mappedToolchainDrive /d | Out-Null
}
