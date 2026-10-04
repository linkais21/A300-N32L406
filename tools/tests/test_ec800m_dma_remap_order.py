"""UART5 RX request selection must be applied to the configured DMA channel."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "src" / "hw_init.c").read_text(encoding="utf-8")
BODY = SOURCE.split("void hw_usart_init(void)", 1)[1].split("void hw_spi_init(void)", 1)[0]

deinit = BODY.index("DMA_DeInit(DMA_CH5);")
init = BODY.index("DMA_Init(DMA_CH5, &dma);")
remap = BODY.index("DMA_RequestRemap(DMA_REMAP_UART5_RX, DMA, DMA_CH5, ENABLE);")
enable = BODY.index("DMA_EnableChannel(DMA_CH5, ENABLE);")

assert deinit < init < remap < enable, "UART5 RX remap must follow DMA5 initialization"
print("EC800M DMA remap order: PASS")
