ENTRY(Reset_Handler)
MEMORY { FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 24K
         RAM (xrw) : ORIGIN = 0x20000000, LENGTH = 24K }
SECTIONS {
  .isr_vector : { KEEP(*(.isr_vector)) } > FLASH
  .text : { *(.text*) *(.rodata*) KEEP(*(.init)) KEEP(*(.fini)) } > FLASH
  .data : {
    _sdata = .;
    *(.data*)
    _edata = .;
  } > RAM AT> FLASH
  _sidata = LOADADDR(.data);
  .bss (NOLOAD) : {
    _sbss = .;
    *(.bss*) *(COMMON)
    _ebss = .;
  } > RAM
  /DISCARD/ : { libc.a(*) libm.a(*) libgcc.a(*) }
}
_boot_end = LOADADDR(.data) + SIZEOF(.data);
ASSERT(_boot_end - ORIGIN(FLASH) <= 0x6000, "bootloader exceeds 24KB release limit")
