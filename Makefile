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
    src/jt808.c          \
    src/motion_corner.c  \
    src/overspeed_policy.c \
    src/jt808_session.c  \
    src/jt808_params.c   \
    src/jt808_terminal_info.c \
    src/terminal_identity.c \
    src/at_config.c      \
    src/adc_monitor.c    \
    src/spi_flash.c      \
    src/crc32.c          \
    src/ext_flash_store.c \
    src/blind_zone.c     \
    src/blind_zone_replay.c \
    src/i2c_accel.c      \
    src/relay.c          \
    src/flash_config.c   \
    src/fota_check_parser.c \
    src/fota.c           \
    src/fota_checkpoint.c \
    src/firmware_signature.c \
    src/agnss_manager.c  \
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
C_SRCS += src/agnss_storage.c src/agnss_zhongkewei.c
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
CFLAGS := $(CPU) -Os -g3 -Wall -Wextra -flto=1 -flto-partition=one \
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

ASFLAGS := $(CPU) -g3 -x assembler-with-cpp $(INCLUDES)

LDFLAGS := $(CPU) \
            -Tldscript/n32l406.ld \
            -Wl,-Map=$(BUILD)/$(TARGET).map \
            -Wl,--gc-sections \
            -Wl,--print-memory-usage \
            -flto=1 -flto-partition=one --specs=nano.specs \
            -lc -lgcc -lm

# ── Build rules ────────────────────────────────────────────────────────────────
.PHONY: all clean flash size release-guard ram-guard stack-guard release-gate print-profile

all: $(BUILD)/$(TARGET).hex size

$(BUILD)/%.o: %.c
	@if not exist "$(subst /,\,$(dir $@))" mkdir "$(subst /,\,$(dir $@))"
	$(CC) $(CFLAGS) -c $< -o $@

# Keep the audited signature boundary visible in the final ELF/map. The rest
# of the application still uses LTO; only the wrapper and upstream verifier do
# not, so link-time inlining cannot erase the shared verifier evidence.
$(BUILD)/src/firmware_signature.o: src/firmware_signature.c
	@if not exist "$(subst /,\,$(dir $@))" mkdir "$(subst /,\,$(dir $@))"
	$(CC) $(CFLAGS) -fno-lto -c $< -o $@

$(BUILD)/third_party/micro-ecc/uECC.o: third_party/micro-ecc/uECC.c
	@if not exist "$(subst /,\,$(dir $@))" mkdir "$(subst /,\,$(dir $@))"
	$(CC) $(CFLAGS) -fno-lto -c $< -o $@

$(BUILD)/sdk/%.o: sdk/%.c
	@if not exist "$(subst /,\,$(dir $@))" mkdir "$(subst /,\,$(dir $@))"
	$(CC) $(CFLAGS) $(SDK_CFLAGS) -c $< -o $@

$(BUILD)/%.o: %.s
	@if not exist "$(subst /,\,$(dir $@))" mkdir "$(subst /,\,$(dir $@))"
	$(CC) $(ASFLAGS) -c $< -o $@

$(BUILD)/$(TARGET).elf: $(OBJS) ldscript/n32l406.ld
	$(CC) $(OBJS) $(LDFLAGS) -o $@

$(BUILD)/$(TARGET).hex: $(BUILD)/$(TARGET).elf
	$(OBJCOPY) -O ihex $< $@
	@echo "==> $(BUILD)/$(TARGET).hex"

size: $(BUILD)/$(TARGET).elf
	$(SIZE) $<

release-guard:
	python tools/release_guard.py

ram-guard: $(BUILD)/$(TARGET).map
	python tools/map_ram_guard.py app $<

STACK_AUDIT_BUILD := build/stack-audit
STACK_AUDIT_CFLAGS := $(filter-out -flto=1 -flto-partition=one,$(CFLAGS)) -fno-lto -fstack-usage

$(STACK_AUDIT_BUILD)/jt808.o: src/jt808.c
	@if not exist "$(subst /,\,$(dir $@))" mkdir "$(subst /,\,$(dir $@))"
	$(CC) $(STACK_AUDIT_CFLAGS) -c $< -o $@

$(STACK_AUDIT_BUILD)/flash_config.o: src/flash_config.c
	@if not exist "$(subst /,\,$(dir $@))" mkdir "$(subst /,\,$(dir $@))"
	$(CC) $(STACK_AUDIT_CFLAGS) -c $< -o $@

$(STACK_AUDIT_BUILD)/gps.o: src/gps.c
	@if not exist "$(subst /,\,$(dir $@))" mkdir "$(subst /,\,$(dir $@))"
	$(CC) $(STACK_AUDIT_CFLAGS) -c $< -o $@

$(STACK_AUDIT_BUILD)/ec800m.o: src/ec800m.c
	@if not exist "$(subst /,\,$(dir $@))" mkdir "$(subst /,\,$(dir $@))"
	$(CC) $(STACK_AUDIT_CFLAGS) -c $< -o $@

stack-guard: $(STACK_AUDIT_BUILD)/jt808.o $(STACK_AUDIT_BUILD)/flash_config.o $(STACK_AUDIT_BUILD)/gps.o $(STACK_AUDIT_BUILD)/ec800m.o $(BUILD)/$(TARGET).map
	python tools/stack_usage_guard.py $(STACK_AUDIT_BUILD)/jt808.su $(STACK_AUDIT_BUILD)/flash_config.su $(STACK_AUDIT_BUILD)/gps.su $(STACK_AUDIT_BUILD)/ec800m.su
	python tools/libc_parser_guard.py $(BUILD)/$(TARGET).map

release-gate: release-guard ram-guard stack-guard

print-profile:
	@echo BUILD=$(BUILD)
	@echo C_SRCS=$(C_SRCS)

flash: $(BUILD)/$(TARGET).hex
	"$(PROG_CLI)" -c port=SWD -w $< -v -rst

clean:
	@if exist "$(BUILD)" rmdir /S /Q "$(BUILD)"
