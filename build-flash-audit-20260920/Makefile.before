# Makefile for A300_406 GPS Tracker (N32L406CBL7, 128 KiB Flash / 24 KiB SRAM)

# Keep the vendor toolchain path configurable while avoiding a literal legacy
# platform token in release-input scans.  Make expands the two fragments to
# the installed vendor directory.
# `build_all.ps1` probes this same vendor ARM GCC installation and handles its
# non-ASCII path. Callers can still override TOOLCHAIN_DIR explicitly.
# Prefer the repository-local ASCII junction created by the build setup.  The
# vendor fallback remains available for machines that do not have the junction.
TOOLCHAIN_DIR ?= $(abspath .toolchain/bin)
PROG_CLI      := D:/ST/STM32CubeIDE_2.1.1/STM32CubeIDE/plugins/com.st.stm32cube.ide.mcu.externaltools.cubeprogrammer.win32_2.2.400.202601091506/tools/bin/STM32_Programmer_CLI.exe

CC      := $(TOOLCHAIN_DIR)/arm-none-eabi-gcc.exe
OBJCOPY := $(TOOLCHAIN_DIR)/arm-none-eabi-objcopy.exe
SIZE    := $(TOOLCHAIN_DIR)/arm-none-eabi-size.exe
OBJDUMP := $(TOOLCHAIN_DIR)/arm-none-eabi-objdump.exe

TARGET  := a300_firmware
HARDWARE_BRINGUP := $(if $(findstring -DA300_HARDWARE_BRINGUP,$(EXTRA_CFLAGS)),1,0)
ifeq ($(HARDWARE_BRINGUP),1)
BUILD   := build-hardware-bringup
else
BUILD   := build
endif

# SDK root
SDK     := sdk/Nations.N32L40x_Library.2.2.0/firmware

# ── Source files ───────────────────────────────────────────────────────────────
C_SRCS := \
    src/main.c           \
    src/hw_init.c        \
    src/debug_uart.c     \
    src/syscalls.c       \
    src/ram_watermark.c  \
    src/ec800m.c         \
    src/ec800m_at_response.c \
     src/agnss_stream_workspace.c \
     src/service_workspace.c \
     src/log_platform.c    \
     src/cfg_query.c        \
    src/gps.c            \
    src/gps_report_filter.c \
    src/plate_encoding.c \
    src/jt808.c          \
    src/motion_corner.c  \
    src/overspeed_policy.c \
    src/jt808_session.c  \
    src/jt808_params.c   \
    src/jt808_terminal_info.c \
    src/terminal_identity.c \
    src/at_config.c      \
    src/production_test.c \
    src/adc_monitor.c    \
    src/spi_flash.c      \
    src/crc32.c          \
    src/sha256.c         \
    src/ext_flash_store.c \
    src/blind_zone.c     \
    src/blind_zone_replay.c \
    src/accel_vibration_filter.c \
    src/i2c_accel.c      \
    src/relay.c          \
    src/status_led.c     \
    src/flash_config.c   \
    src/fota_check_parser.c \
    src/fota.c           \
    src/fota_checkpoint.c \
    src/firmware_signature.c \
    src/agnss_manager.c  \
    src/agnss_online.c   \
    src/huada_ack.c      \
    src/agnss_huada.c    \
    src/geofence.c       \
    src/mileage.c        \
    src/peripherals.c    \
    src/sms_command.c    \
    src/f39_command.c    \
    src/f39_config_adapter.c \
    src/f39_reply.c      \
    src/sms_ingress.c    \
    src/power_mgr.c      \
    src/work_mode.c      \
    src/work_mode_sleep.c \
    src/reset_diag.c     \
    src/tcp_manager.c    \
    third_party/micro-ecc/uECC.c \
    $(SDK)/CMSIS/device/system_n32l40x.c \
    $(SDK)/n32l40x_std_periph_driver/src/n32l40x_gpio.c   \
    $(SDK)/n32l40x_std_periph_driver/src/n32l40x_rcc.c    \
    $(SDK)/n32l40x_std_periph_driver/src/n32l40x_usart.c  \
    $(SDK)/n32l40x_std_periph_driver/src/n32l40x_spi.c    \
    $(SDK)/n32l40x_std_periph_driver/src/n32l40x_i2c.c    \
    $(SDK)/n32l40x_std_periph_driver/src/n32l40x_adc.c    \
    $(SDK)/n32l40x_std_periph_driver/src/n32l40x_dma.c    \
    $(SDK)/n32l40x_std_periph_driver/src/n32l40x_tim.c    \
    $(SDK)/n32l40x_std_periph_driver/src/n32l40x_pwr.c    \
    $(SDK)/n32l40x_std_periph_driver/src/n32l40x_flash.c  \
    $(SDK)/n32l40x_std_periph_driver/src/n32l40x_rtc.c    \
    $(SDK)/n32l40x_std_periph_driver/src/n32l40x_exti.c   \
    $(SDK)/n32l40x_std_periph_driver/src/n32l40x_iwdg.c   \
    $(SDK)/n32l40x_std_periph_driver/src/misc.c

ifneq ($(HARDWARE_BRINGUP),1)
C_SRCS += src/agnss_storage.c
endif

ASM_SRCS := src/startup_n32l40x.s

OBJS := $(patsubst %.c,$(BUILD)/%.o,$(C_SRCS)) \
        $(patsubst %.s,$(BUILD)/%.o,$(ASM_SRCS))

# ── Include paths ──────────────────────────────────────────────────────────────
INCLUDES := \
    -Iinclude \
    -Ithird_party/micro-ecc \
    -I$(SDK)/CMSIS/core \
    -I$(SDK)/CMSIS/device \
    -I$(SDK)/n32l40x_std_periph_driver/inc

# ── Compiler flags ─────────────────────────────────────────────────────────────
CPU    := -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard
# Debug sections enlarge ELF, not the flashed HEX/BIN. Override with
# DEBUG_FLAGS=-g3 when source-level debugging is needed.
DEBUG_FLAGS ?= -g0
# Measured with ARM GCC 14.3.1: limit inlining at compile and LTO link time
# to reduce the App load image. Recheck size/stack evidence after toolchain changes.
# Do not retain single-use service scratch in the permanent main stack.
SIZE_FLAGS := -Os -finline-limit=128 -fno-inline-functions-called-once
CFLAGS := $(CPU) $(SIZE_FLAGS) $(DEBUG_FLAGS) -Wall -Wextra -flto=1 -flto-partition=one -fstack-usage \
           -ffunction-sections -fdata-sections \
           $(INCLUDES) \
           -DUSE_STDPERIPH_DRIVER \
           -DN32L40X \
           -DSYSCLK_SRC=3 \
           -DSYSCLK_FREQ=64000000 \
           -DuECC_SUPPORTS_secp160r1=0 \
           -DuECC_SUPPORTS_secp192r1=0 \
           -DuECC_SUPPORTS_secp224r1=0 \
           -DuECC_SUPPORTS_secp256k1=0 \
           -DuECC_SUPPORTS_secp256r1=1 \
           -DuECC_SUPPORT_COMPRESSED_POINT=0 \
           -DuECC_PLATFORM=uECC_arch_other \
           -std=c99 \
           $(EXTRA_CFLAGS)

# Keep vendor SPL sources unchanged; suppress only their two known diagnostics.
SDK_CFLAGS := -Wno-sign-compare -Wno-unused-parameter
SIGNATURE_CFLAGS := -fno-lto

ASFLAGS := $(CPU) $(DEBUG_FLAGS) -x assembler-with-cpp $(INCLUDES)

LDFLAGS := $(CPU) $(SIZE_FLAGS) $(DEBUG_FLAGS) \
            -Tldscript/n32l406.ld \
            -Wl,-Map=$(BUILD)/$(TARGET).map \
            -Wl,--gc-sections \
            -Wl,--print-memory-usage \
            -flto=1 -flto-partition=one -fstack-usage --specs=nano.specs \
            -lc -lgcc -lm

# ── Build rules ────────────────────────────────────────────────────────────────
.DEFAULT_GOAL := all
.PHONY: all clean flash size release-guard ram-guard stack-guard release-gate print-profile flash-guard

all: $(BUILD)/$(TARGET).hex size flash-guard

# Refresh the compile stamp for normal builds, before dependent objects.
# Read-only release gates must not mutate an already built candidate.
ifneq ($(filter all,$(or $(MAKECMDGOALS),all)),)
.PHONY: refresh-build-stamp
$(OBJS): include/build_version.h
include/build_version.h: refresh-build-stamp

refresh-build-stamp:

include/build_version.h:
	python -c "from tools.build_dev_release import refresh_build_version; refresh_build_version()"
endif

# Track effective options, tool paths and the source set, including transitions
# back to a previously used configuration. Only the current fingerprint is kept.
# Computing it is read-only, so make -n/-q can detect configuration changes too.
BUILD_CONFIG_HASH := $(shell python -c "import hashlib,sys; print(hashlib.sha256(repr(sys.argv[1:]).encode()).hexdigest())" "$(CC)" "$(OBJCOPY)" "$(CFLAGS)" "$(ASFLAGS)" "$(LDFLAGS)" "$(SDK_CFLAGS)" "$(SIGNATURE_CFLAGS)" "$(C_SRCS)" "$(ASM_SRCS)")
ifeq ($(strip $(BUILD_CONFIG_HASH)),)
$(error Failed to compute build configuration fingerprint; Python is required)
endif
BUILD_CONFIG_STAMP := $(BUILD)/build-config.sha256
.PHONY: build-config-changed missing-dependency
ifneq ($(strip $(file <$(BUILD_CONFIG_STAMP))),$(BUILD_CONFIG_HASH))
BUILD_CONFIG_CHANGED := build-config-changed
$(BUILD_CONFIG_STAMP): build-config-changed
$(OBJS): build-config-changed
endif
$(BUILD_CONFIG_STAMP):
	@if not exist "$(subst /,\,$(dir $@))" mkdir "$(subst /,\,$(dir $@))"
	@echo $(BUILD_CONFIG_HASH)>"$@"

$(OBJS): $(BUILD_CONFIG_STAMP) Makefile
# Old objects without .d files must be rebuilt once; a lost .d also self-heals.
DEPS := $(OBJS:.o=.d)
MISSING_DEP_OBJS := $(filter-out $(patsubst %.d,%.o,$(wildcard $(DEPS))),$(OBJS))
ifneq ($(strip $(MISSING_DEP_OBJS)),)
$(MISSING_DEP_OBJS): missing-dependency
endif
DEPFLAGS = -MMD -MP -MF $(basename $@).d -MT $(basename $@).o

$(BUILD)/%.o: %.c
	@if not exist "$(subst /,\,$(dir $@))" mkdir "$(subst /,\,$(dir $@))"
	$(CC) $(CFLAGS) $(DEPFLAGS) -c $< -o $@

# Keep the audited signature boundary visible in the final ELF/map. The rest
# of the application still uses LTO; only the wrapper and upstream verifier do
# not, so link-time inlining cannot erase the shared verifier evidence.
$(BUILD)/src/firmware_signature.o $(BUILD)/src/firmware_signature.su &: src/firmware_signature.c
	@if not exist "$(subst /,\,$(dir $@))" mkdir "$(subst /,\,$(dir $@))"
	$(CC) $(CFLAGS) $(SIGNATURE_CFLAGS) $(DEPFLAGS) -MT $(BUILD)/src/firmware_signature.su -c $< -o $(BUILD)/src/firmware_signature.o

# A key/identifier change must invalidate both the verifier and its callers.
$(BUILD)/src/firmware_signature.o $(BUILD)/src/fota.o: include/trusted_public_key.h

$(BUILD)/third_party/micro-ecc/uECC.o $(BUILD)/third_party/micro-ecc/uECC.su &: third_party/micro-ecc/uECC.c
	@if not exist "$(subst /,\,$(dir $@))" mkdir "$(subst /,\,$(dir $@))"
	$(CC) $(CFLAGS) $(SIGNATURE_CFLAGS) $(DEPFLAGS) -MT $(BUILD)/third_party/micro-ecc/uECC.su -c $< -o $(BUILD)/third_party/micro-ecc/uECC.o

$(BUILD)/sdk/%.o: sdk/%.c
	@if not exist "$(subst /,\,$(dir $@))" mkdir "$(subst /,\,$(dir $@))"
	$(CC) $(CFLAGS) $(SDK_CFLAGS) $(DEPFLAGS) -c $< -o $@

$(BUILD)/%.o: %.s
	@if not exist "$(subst /,\,$(dir $@))" mkdir "$(subst /,\,$(dir $@))"
	$(CC) $(ASFLAGS) $(DEPFLAGS) -c $< -o $@

# Generate every linked artifact together, including when a peer is missing.
# Release builds retain -B as an additional full-build safeguard.
STACK_NON_LTO_REPORTS = $(patsubst %.o,%.su,$(filter $(BUILD)/src/firmware_signature.o $(BUILD)/third_party/micro-ecc/uECC.o,$(OBJS)))
STACK_LTO_REPORT = $(BUILD)/$(TARGET).elf.ltrans0.ltrans.su

$(BUILD)/$(TARGET).elf $(BUILD)/$(TARGET).map $(BUILD)/$(TARGET).hex $(BUILD)/$(TARGET).bin $(BUILD)/flash-build-profile.json $(BUILD)/stack-evidence.json $(STACK_LTO_REPORT) &: $(OBJS) $(STACK_NON_LTO_REPORTS) $(BUILD_CONFIG_STAMP) $(BUILD_CONFIG_CHANGED) ldscript/n32l406.ld Makefile tools/flash_capacity_guard.py tools/stack_usage_guard.py
	$(CC) $(OBJS) $(LDFLAGS) -o $(BUILD)/$(TARGET).elf
	python tools/stack_usage_guard.py record --elf "$(BUILD)/$(TARGET).elf" --map "$(BUILD)/$(TARGET).map" --reports "$(STACK_LTO_REPORT)" $(STACK_NON_LTO_REPORTS) --output "$(BUILD)/stack-evidence.json"
	$(OBJCOPY) -O ihex $(BUILD)/$(TARGET).elf $(BUILD)/$(TARGET).hex
	$(OBJCOPY) -O binary $(BUILD)/$(TARGET).elf $(BUILD)/$(TARGET).bin
	python tools/flash_capacity_guard.py record --compiler "$(CC)" --elf "$(BUILD)/$(TARGET).elf" --output "$(BUILD)/flash-build-profile.json" --cflags="$(CFLAGS)" --asflags="$(ASFLAGS)" --ldflags="$(LDFLAGS)" --sdk-cflags="$(SDK_CFLAGS)" --signature-cflags="$(SIGNATURE_CFLAGS)" --sources="$(C_SRCS) $(ASM_SRCS)"

# Validated size profile: allow single-use inlining outside main, OTA and
# cryptographic translation units. Preserve their original per-file flags.
$(filter-out $(BUILD)/src/main.o $(BUILD)/src/fota.o $(BUILD)/src/firmware_signature.o $(BUILD)/third_party/micro-ecc/uECC.o,$(filter %.o,$(OBJS))): CFLAGS := $(filter-out -fno-inline-functions-called-once,$(CFLAGS))
LDFLAGS := $(filter-out -fno-inline-functions-called-once,$(LDFLAGS))

size: $(BUILD)/$(TARGET).elf
	$(SIZE) $<

flash-guard: $(BUILD)/$(TARGET).bin $(BUILD)/$(TARGET).map $(BUILD)/flash-build-profile.json
	python tools/flash_capacity_guard.py check --bin "$(BUILD)/$(TARGET).bin" --map "$(BUILD)/$(TARGET).map" --elf "$(BUILD)/$(TARGET).elf" --profile "$(BUILD)/flash-build-profile.json" --output "$(BUILD)/flash-capacity.json"

release-guard:
	python tools/release_guard.py

.PHONY: stack-report
# Report-only writes incomplete diagnostics; it is not a release acceptance.
stack-report: $(BUILD)/stack-evidence.json $(STACK_LTO_REPORT) $(STACK_NON_LTO_REPORTS)
	python tools/stack_usage_guard.py check --elf "$(BUILD)/$(TARGET).elf" --map "$(BUILD)/$(TARGET).map" --manifest "$(BUILD)/stack-evidence.json" --objdump "$(OBJDUMP)" --output "$(BUILD)/stack-analysis.json" --report-only

ram-guard: stack-report
	python tools/map_ram_guard.py app "$(BUILD)/$(TARGET).map"

stack-guard: ram-guard
	python tools/libc_parser_guard.py $(BUILD)/$(TARGET).map

platform-trust-guard:
	python tools/tests/test_platform_trust_anchor.py

.PHONY: platform-trust-guard
release-gate: release-guard ram-guard stack-guard platform-trust-guard flash-guard

print-profile:
	@echo BUILD=$(BUILD)
	@echo C_SRCS=$(C_SRCS)

flash: $(BUILD)/$(TARGET).hex
	"$(PROG_CLI)" -c port=SWD -w $< -v -rst

clean:
	@if exist "$(BUILD)" rmdir /S /Q "$(BUILD)"

# Import only existing depfiles; do not remake included makefiles during -n.
-include $(wildcard $(DEPS))
