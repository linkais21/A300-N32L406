C_SRCS := $(filter-out src/sha256.c,$(C_SRCS))
OBJS := $(filter-out $(BUILD)/src/sha256.o,$(OBJS))
$(BUILD)/src/fota.o: build/hil-stability-20260913/rx-only-source/src/fota.c
	@if not exist "$(subst /,\,$(dir $@))" mkdir "$(subst /,\,$(dir $@))"
	$(CC) $(CFLAGS) -MMD -MP -MF $(@:.o=.d) -MT $@ -c $< -o $@
$(BUILD)/src/agnss_storage.o: build/hil-stability-20260913/rx-only-source/src/agnss_storage.c
	@if not exist "$(subst /,\,$(dir $@))" mkdir "$(subst /,\,$(dir $@))"
	$(CC) $(CFLAGS) -MMD -MP -MF $(@:.o=.d) -MT $@ -c $< -o $@
