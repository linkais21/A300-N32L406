######################################
# target
######################################
TARGET = RT_Thread15_TIM_DEVICE_REGISTER


######################################
# building variables
######################################
# debug build?
DEBUG = 1
# optimization
OPT = -Og


#######################################
# paths
#######################################
# Build path
BUILD_DIR = build

######################################
# source
######################################
# C sources
PROJECT_ROOT = ../../../../../../
C_SOURCES =  \
$(PROJECT_ROOT)/projects/n32l40x_EVAL/examples/RT_Thread/RT_Thread15_TIM_DEVICE_REGISTER/src/main.c \
$(PROJECT_ROOT)/projects/n32l40x_EVAL/examples/RT_Thread/RT_Thread15_TIM_DEVICE_REGISTER/src/n32l40x_it.c \
$(PROJECT_ROOT)/projects/n32l40x_EVAL/examples/RT_Thread/RT_Thread15_TIM_DEVICE_REGISTER/src/board.c \
$(PROJECT_ROOT)/firmware/CMSIS/device/system_n32l40x.c \
$(PROJECT_ROOT)/firmware/n32l40x_std_periph_driver/src/misc.c \
$(PROJECT_ROOT)/firmware/n32l40x_std_periph_driver/src/n32l40x_gpio.c \
$(PROJECT_ROOT)/firmware/n32l40x_std_periph_driver/src/n32l40x_rcc.c \
$(PROJECT_ROOT)/firmware/n32l40x_std_periph_driver/src/n32l40x_usart.c \
$(PROJECT_ROOT)/firmware/n32l40x_std_periph_driver/src/n32l40x_exti.c \
$(PROJECT_ROOT)/firmware/n32l40x_std_periph_driver/src/n32l40x_tim.c \
$(PROJECT_ROOT)/middlewares/rt-thread/src/clock.c \
$(PROJECT_ROOT)/middlewares/rt-thread/src/device.c \
$(PROJECT_ROOT)/middlewares/rt-thread/src/idle.c \
$(PROJECT_ROOT)/middlewares/rt-thread/src/ipc.c \
$(PROJECT_ROOT)/middlewares/rt-thread/src/irq.c \
$(PROJECT_ROOT)/middlewares/rt-thread/src/kservice.c \
$(PROJECT_ROOT)/middlewares/rt-thread/src/mem.c \
$(PROJECT_ROOT)/middlewares/rt-thread/src/memheap.c \
$(PROJECT_ROOT)/middlewares/rt-thread/src/mempool.c \
$(PROJECT_ROOT)/middlewares/rt-thread/src/object.c \
$(PROJECT_ROOT)/middlewares/rt-thread/src/scheduler.c \
$(PROJECT_ROOT)/middlewares/rt-thread/src/slab.c \
$(PROJECT_ROOT)/middlewares/rt-thread/src/thread.c \
$(PROJECT_ROOT)/middlewares/rt-thread/src/timer.c \
$(PROJECT_ROOT)/middlewares/rt-thread/src/components.c \
$(PROJECT_ROOT)/middlewares/rt-thread/src/cpu.c \
$(PROJECT_ROOT)/middlewares/rt-thread/src/signal.c \
$(PROJECT_ROOT)/middlewares/rt-thread/libcpu/cortex-m4/cpuport.c \
$(PROJECT_ROOT)/projects/n32l40x_EVAL/examples/RT_Thread/DeviceDrivers/gpio/src/drv_gpio.c \
$(PROJECT_ROOT)/projects/n32l40x_EVAL/examples/RT_Thread/DeviceDrivers/uart/src/drv_usart.c \
$(PROJECT_ROOT)/projects/n32l40x_EVAL/examples/RT_Thread/DeviceDrivers/tim/src/drv_hwtimer.c \
$(PROJECT_ROOT)/middlewares/rt-thread/components/drivers/serial/serial.c \
$(PROJECT_ROOT)/middlewares/rt-thread/components/drivers/src/completion.c \
$(PROJECT_ROOT)/middlewares/rt-thread/components/drivers/misc/pin.c \
$(PROJECT_ROOT)/middlewares/rt-thread/components/drivers/hwtimer/hwtimer.c


# ASM sources
ASM_SOURCES =  \
$(PROJECT_ROOT)/firmware/CMSIS/device/startup/startup_n32l40x_gcc.s  \
$(PROJECT_ROOT)/middlewares/rt-thread/libcpu/cortex-m4/context_gcc.s

#######################################
# binaries
#######################################
PREFIX = arm-none-eabi-
# The gcc compiler bin path can be either defined in make command via GCC_PATH variable (> make GCC_PATH=xxx)
# either it can be added to the PATH environment variable.
ifdef GCC_PATH
CC = $(GCC_PATH)/$(PREFIX)gcc
AS = $(GCC_PATH)/$(PREFIX)gcc -x assembler-with-cpp
CP = $(GCC_PATH)/$(PREFIX)objcopy
SZ = $(GCC_PATH)/$(PREFIX)size
else
CC = $(PREFIX)gcc
AS = $(PREFIX)gcc -x assembler-with-cpp
CP = $(PREFIX)objcopy
SZ = $(PREFIX)size
endif
HEX = $(CP) -O ihex
BIN = $(CP) -O binary -S
 
#######################################
# CFLAGS
#######################################
# cpu
CPU = -mcpu=cortex-m4

# fpu
FPU = -mfpu=fpv4-sp-d16

# float-abi
#FLOAT-ABI = -mfloat-abi=hardloat
FLOAT-ABI = -mfloat-abi=soft

# mcu
MCU = $(CPU) -mthumb $(FPU) $(FLOAT-ABI)

# macros for gcc
# AS defines
AS_DEFS = 

# C defines
C_DEFS =  \
-DUSE_STDPERIPH_DRIVER \
-Dn32l40x


# AS includes
AS_INCLUDES = 


# C includes
C_INCLUDES =  \
-I$(PROJECT_ROOT)/firmware/n32l40x_std_periph_driver/inc \
-I$(PROJECT_ROOT)/projects/n32l40x_EVAL/examples/RT_Thread/RT_Thread15_TIM_DEVICE_REGISTER/inc \
-I$(PROJECT_ROOT)/middlewares/rt-thread/include \
-I$(PROJECT_ROOT)/projects/n32l40x_EVAL/examples/RT_Thread/DeviceDrivers/gpio/inc \
-I$(PROJECT_ROOT)/projects/n32l40x_EVAL/examples/RT_Thread/DeviceDrivers/uart/inc \
-I$(PROJECT_ROOT)/projects/n32l40x_EVAL/examples/RT_Thread/DeviceDrivers/tim/inc \
-I$(PROJECT_ROOT)/firmware/CMSIS/device \
-I$(PROJECT_ROOT)/firmware/CMSIS/core \
-I$(PROJECT_ROOT)/middlewares/rt-thread/components/drivers/include/drivers \
-I$(PROJECT_ROOT)/middlewares/rt-thread/components/drivers/include \
-I$(PROJECT_ROOT)/middlewares/rt-thread/components/drivers/include/ipc

# compile gcc flags
ASFLAGS = $(MCU) $(AS_DEFS) $(AS_INCLUDES) $(OPT) -Wall -fdata-sections -ffunction-sections

CFLAGS += $(MCU) $(C_DEFS) $(C_INCLUDES) $(OPT) -Wall -fdata-sections -ffunction-sections

ifeq ($(DEBUG), 1)
CFLAGS += -g -gdwarf-2
endif


# Generate dependency information
CFLAGS += -MMD -MP -MF"$(@:%.o=%.d)"


#######################################
# LDFLAGS
#######################################
# link script
LDSCRIPT = $(PROJECT_ROOT)/firmware/CMSIS/device/n32l40x_flash.ld

# libraries
LIBS = -lc -lm -lnosys 
LIBDIR = 
LDFLAGS = $(MCU) -specs=nano.specs -T$(LDSCRIPT) $(LIBDIR) $(LIBS) -Wl,-Map=$(BUILD_DIR)/$(TARGET).map,--cref -Wl,--gc-sections

# default action: build all
all: $(BUILD_DIR)/$(TARGET).elf $(BUILD_DIR)/$(TARGET).hex $(BUILD_DIR)/$(TARGET).bin

#######################################
# build the application
#######################################
# list of objects
OBJECTS = $(addprefix $(BUILD_DIR)/,$(notdir $(C_SOURCES:.c=.o)))
vpath %.c $(sort $(dir $(C_SOURCES)))
# list of ASM program objects
OBJECTS += $(addprefix $(BUILD_DIR)/,$(notdir $(ASM_SOURCES:.s=.o)))
vpath %.s $(sort $(dir $(ASM_SOURCES)))

$(BUILD_DIR)/%.o: %.c Makefile | $(BUILD_DIR) 
	$(CC) -c $(CFLAGS) -Wa,-a,-ad,-alms=$(BUILD_DIR)/$(notdir $(<:.c=.lst)) $< -o $@

$(BUILD_DIR)/%.o: %.s Makefile | $(BUILD_DIR)
	$(AS) -c $(CFLAGS) $< -o $@

$(BUILD_DIR)/$(TARGET).elf: $(OBJECTS) Makefile
	$(CC) $(OBJECTS) $(LDFLAGS) -o $@
	$(SZ) $@

$(BUILD_DIR)/%.hex: $(BUILD_DIR)/%.elf | $(BUILD_DIR)
	$(HEX) $< $@
	
$(BUILD_DIR)/%.bin: $(BUILD_DIR)/%.elf | $(BUILD_DIR)
	$(BIN) $< $@	
	
$(BUILD_DIR):
	mkdir $@		

#######################################
# clean up
#######################################
clean:
	-del -rf $(BUILD_DIR)
  
#######################################
# dependencies
#######################################
-include $(wildcard $(BUILD_DIR)/*.d)

# *** EOF ***
