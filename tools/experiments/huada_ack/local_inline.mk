# Isolated candidate: keep main, FOTA and signature compilation unchanged.
INLINE_LIMIT ?= 64
INLINE_OPT ?= -Os
$(filter-out $(BUILD)/src/main.o $(BUILD)/src/fota.o $(BUILD)/src/firmware_signature.o $(BUILD)/third_party/micro-ecc/uECC.o,$(filter %.o,$(OBJS))): CFLAGS := $(filter-out -Os -fno-inline-functions-called-once -finline-limit=64,$(CFLAGS)) $(INLINE_OPT) -finline-limit=$(INLINE_LIMIT)
LDFLAGS := $(filter-out -fno-inline-functions-called-once,$(LDFLAGS))
