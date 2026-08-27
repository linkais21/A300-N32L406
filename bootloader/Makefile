CC ?= arm-none-eabi-gcc
OBJCOPY ?= arm-none-eabi-objcopy
SIZE ?= arm-none-eabi-size
CFLAGS := -mcpu=cortex-m4 -mthumb -Os -ffunction-sections -fdata-sections -ffreestanding -std=c99 -Iinclude
LDFLAGS := -mcpu=cortex-m4 -mthumb -nostartfiles -Wl,--gc-sections -Tldscript/n32l406_boot.ld -Wl,-Map=build/bootloader.map
SRCS := src/main.c src/bcr.c src/image_verify.c src/image_install.c
OBJS := $(SRCS:src/%.c=build/%.o) build/startup_n32l40x.o
all: build/bootloader.elf
build:
	@mkdir -p build
build/%.o: src/%.c | build
	$(CC) $(CFLAGS) -c $< -o $@
build/startup_n32l40x.o: src/startup_n32l40x.s | build
	$(CC) $(CFLAGS) -x assembler-with-cpp -c $< -o $@
build/bootloader.elf: $(OBJS)
	$(CC) $(LDFLAGS) $^ -o $@
	$(SIZE) $@
clean:
	rm -rf build
.PHONY: all clean
