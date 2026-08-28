# Makefile for A300_406 GPS Tracker (N32L406CDL7)

TOOLCHAIN_DIR := D:/SofWare/STM32CubeIDE_2.1.1/STM32CubeIDE/plugins/com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32.14.3.rel1.win32_1.0.100.202602081740/tools/bin
PROG_CLI      := D:/SofWare/STM32CubeIDE_2.1.1/STM32CubeIDE/plugins/com.st.stm32cube.ide.mcu.externaltools.cubeprogrammer.win32_2.2.400.202601091506/tools/bin/STM32_Programmer_CLI.exe

CC      := $(TOOLCHAIN_DIR)/arm-none-eabi-gcc.exe
OBJCOPY := $(TOOLCHAIN_DIR)/arm-none-eabi-objcopy.exe
SIZE    := $(TOOLCHAIN_DIR)/arm-none-eabi-size.exe

TARGET  := a300_firmware
BUILD   := build

# SDK root
SDK     := sdk/Nations.N32L40x_Library.2.2.0/firmware

# ── Source files ───────────────────────────────────────────────────────────────
C_SRCS := \
    src/main.c           \
    src/hw_init.c        \
    src/debug_uart.c     \
    src/syscalls.c       \
    src/ec800m.c         \
    src/gps.c            \
    src/jt808.c          \
    src/jt808_params.c   \
    src/at_config.c      \
    src/adc_monitor.c    \
    src/spi_flash.c      \
    src/ext_flash_store.c \
    src/i2c_accel.c      \
    src/relay.c          \
    src/flash_config.c   \
    src/fota.c           \
    src/agnss_storage.c  \
    src/agnss_manager.c  \
    src/agnss_huada.c    \
    src/agnss_zhongkewei.c \
    src/geofence.c       \
    src/mileage.c        \
    src/peripherals.c    \
    src/sms_command.c    \
    src/sms_ingress.c    \
    src/power_mgr.c      \
    src/tcp_manager.c    \
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

ASM_SRCS := src/startup_n32l40x.s

OBJS := $(patsubst %.c,$(BUILD)/%.o,$(C_SRCS)) \
        $(patsubst %.s,$(BUILD)/%.o,$(ASM_SRCS))

# ── Include paths ──────────────────────────────────────────────────────────────
INCLUDES := \
    -Iinclude \
    -I$(SDK)/CMSIS/core \
    -I$(SDK)/CMSIS/device \
    -I$(SDK)/n32l40x_std_periph_driver/inc

# ── Compiler flags ─────────────────────────────────────────────────────────────
CPU    := -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard
CFLAGS := $(CPU) -O2 -g3 -Wall -Wextra \
           -ffunction-sections -fdata-sections \
           $(INCLUDES) \
           -DUSE_STDPERIPH_DRIVER \
           -DN32L40X \
           -DSYSCLK_SRC=3 \
           -DSYSCLK_FREQ=64000000 \
           -std=c99

ASFLAGS := $(CPU) -g3 -x assembler-with-cpp $(INCLUDES)

LDFLAGS := $(CPU) \
            -Tldscript/n32l406.ld \
            -Wl,-Map=$(BUILD)/$(TARGET).map \
            -Wl,--gc-sections \
            -Wl,--print-memory-usage \
            -lc -lgcc -lm

# ── Build rules ────────────────────────────────────────────────────────────────
.PHONY: all clean flash size release-guard ram-guard release-gate

all: $(BUILD)/$(TARGET).hex size

$(BUILD)/%.o: %.c
	@if not exist "$(subst /,\,$(dir $@))" mkdir "$(subst /,\,$(dir $@))"
	$(CC) $(CFLAGS) -c $< -o $@

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
	python tools/map_ram_guard.py $<

release-gate: release-guard ram-guard

flash: $(BUILD)/$(TARGET).hex
	"$(PROG_CLI)" -c port=SWD -w $< -v -rst

clean:
	rm -rf $(BUILD)
