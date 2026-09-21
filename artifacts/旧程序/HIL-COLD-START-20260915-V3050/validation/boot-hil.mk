TOOLCHAIN_ROOT ?= $(abspath ../.toolchain/bin)
SDK := ../sdk/Nations.N32L40x_Library.2.2.0/firmware
CC := $(TOOLCHAIN_ROOT)/arm-none-eabi-gcc.exe
OBJCOPY := $(TOOLCHAIN_ROOT)/arm-none-eabi-objcopy.exe
SIZE := $(TOOLCHAIN_ROOT)/arm-none-eabi-size.exe
CFLAGS := -mcpu=cortex-m4 -mthumb -Os -Wall -Wextra -ffunction-sections -fdata-sections -ffreestanding -std=c99 -Iinclude -I../include -I../third_party/micro-ecc -I$(SDK)/CMSIS/core -I$(SDK)/CMSIS/device -I$(SDK)/n32l40x_std_periph_driver/inc -DUSE_STDPERIPH_DRIVER -DN32L40X -DSYSCLK_SRC=3 -DSYSCLK_FREQ=64000000 -DuECC_SUPPORTS_secp160r1=0 -DuECC_SUPPORTS_secp192r1=0 -DuECC_SUPPORTS_secp224r1=0 -DuECC_SUPPORTS_secp256k1=0 -DuECC_SUPPORTS_secp256r1=1 -DuECC_SUPPORT_COMPRESSED_POINT=0 -DuECC_PLATFORM=uECC_arch_other
SDK_CFLAGS := -Wno-sign-compare -Wno-unused-parameter
LDFLAGS := -mcpu=cortex-m4 -mthumb -nostartfiles -Wl,--gc-sections -Tldscript/n32l406_boot.ld -Wl,-Map=../build/cold-start-3050/boot/bootloader.map
SRCS := src/main.c src/bcr.c src/image_verify.c src/image_install.c src/factory_init.c src/platform_n32l406.c src/boot_progress.c
SDK_SRCS := $(SDK)/CMSIS/device/system_n32l40x.c \
            $(SDK)/n32l40x_std_periph_driver/src/n32l40x_usart.c \
            $(SDK)/n32l40x_std_periph_driver/src/n32l40x_gpio.c \
            $(SDK)/n32l40x_std_periph_driver/src/n32l40x_rcc.c \
            $(SDK)/n32l40x_std_periph_driver/src/n32l40x_spi.c \
            $(SDK)/n32l40x_std_periph_driver/src/n32l40x_flash.c \
            $(SDK)/n32l40x_std_periph_driver/src/n32l40x_iwdg.c
OBJS := $(SRCS:src/%.c=../build/cold-start-3050/boot/%.o) ../build/cold-start-3050/boot/firmware_signature.o ../build/cold-start-3050/boot/uECC.o \
        $(SDK_SRCS:../%.c=../build/cold-start-3050/boot/sdk/%.o) ../build/cold-start-3050/boot/startup_n32l40x.o
all: ../build/cold-start-3050/boot/bootloader.hex ../build/cold-start-3050/boot/bootloader.bin
../build/cold-start-3050/boot:
	@if not exist "../build/cold-start-3050/boot" mkdir "../build/cold-start-3050/boot"
../build/cold-start-3050/boot/%.o: src/%.c | ../build/cold-start-3050/boot
	$(CC) $(CFLAGS) -c $< -o $@
../build/cold-start-3050/boot/sdk/%.o: ../%.c | ../build/cold-start-3050/boot
	@if not exist "$(subst /,\,$(dir $@))" mkdir "$(subst /,\,$(dir $@))"
	$(CC) $(CFLAGS) $(SDK_CFLAGS) -c $< -o $@
../build/cold-start-3050/boot/firmware_signature.o: ../src/firmware_signature.c | ../build/cold-start-3050/boot
	$(CC) $(CFLAGS) -c $< -o $@
../build/cold-start-3050/boot/firmware_signature.o ../build/cold-start-3050/boot/image_verify.o: ../include/trusted_public_key.h
../build/cold-start-3050/boot/main.o: ../include/build_version.h
../build/cold-start-3050/boot/uECC.o: ../third_party/micro-ecc/uECC.c | ../build/cold-start-3050/boot
	$(CC) $(CFLAGS) -c $< -o $@
../build/cold-start-3050/boot/startup_n32l40x.o: src/startup_n32l40x.s | ../build/cold-start-3050/boot
	$(CC) $(CFLAGS) -x assembler-with-cpp -c $< -o $@
../build/cold-start-3050/boot/bootloader.elf: $(OBJS)
	$(CC) $(LDFLAGS) $^ -o $@
	$(SIZE) $@
../build/cold-start-3050/boot/bootloader.hex: ../build/cold-start-3050/boot/bootloader.elf
	$(OBJCOPY) -O ihex $< $@
../build/cold-start-3050/boot/bootloader.bin: ../build/cold-start-3050/boot/bootloader.elf
	$(OBJCOPY) -O binary $< $@
clean:
	@if exist "../build/cold-start-3050/boot" rmdir /S /Q "../build/cold-start-3050/boot"
.PHONY: all clean
