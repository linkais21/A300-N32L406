from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=root/'src/i2c_accel.c'
s=p.read_text(encoding='utf-8')
start=s.index('            bool int1_config_ok =')
end=s.index('            /* Reset any event latched',start)
s=s[:start]+'''            /* Preserve register order and stop on the first failed write.
             * Active motion wakes STOP; software confirms six seconds.
             * Latch one event until that decision consumes it. */
            static const uint8_t setup[][2] = {
                {DA218E_REG_RANGE, DA218E_RANGE_2G},
                {DA218E_REG_ODR_AXIS, DA218E_ODR_125HZ},
                {DA218E_REG_MODE_BW, DA218E_MODE_NORMAL},
                {DA218E_REG_INT_CONFIG, 0x81U},
                {DA218E_REG_INT_CONFIG, 0x01U},
                {DA218E_REG_INT_SET1, 0x83U},
                {DA218E_REG_INT_MAP1, 0x04U},
                {DA218E_REG_INT_LATCH, 0x07U},
                {DA218E_REG_ACTIVE_DUR, 0x00U},
                {DA218E_REG_ACTIVE_THS, 0x26U},
            };
            bool int1_config_ok = true;
            for (unsigned reg = 0U; reg < sizeof(setup)/sizeof(setup[0]); ++reg) {
                if (!i2c_write_reg(setup[reg][0], setup[reg][1])) {
                    int1_config_ok = false;
                    break;
                }
            }
'''+s[end:]
p.write_text(s,encoding='utf-8',newline='\n')
