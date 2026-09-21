ENTRY(Reset_Handler)
MEMORY { FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 22K
         FACTORY_INIT (rx) : ORIGIN = 0x08005800, LENGTH = 2K
         RAM (xrw) : ORIGIN = 0x20000000, LENGTH = 24K }
SECTIONS {
  .isr_vector : { KEEP(*(.isr_vector)) } > FLASH
  .text : { *(.text*) *(.rodata*) KEEP(*(.init)) KEEP(*(.fini)) } > FLASH
  .ARM.extab : { *(.ARM.extab*) } > FLASH
  .ARM.exidx : { *(.ARM.exidx*) } > FLASH
  .data : {
    _sdata = .;
    *(.data*)
    _edata = .;
  } > RAM AT> FLASH
  _sidata = LOADADDR(.data);
  _boot_code_end = LOADADDR(.data) + SIZEOF(.data);
  .factory_init_request 0x08005800 : {
    KEEP(*(.factory_init_request))
  } > FACTORY_INIT
  .bss (NOLOAD) : {
    _sbss = .;
    *(.bss*) *(COMMON)
    _ebss = .;
  } > RAM
  /DISCARD/ : { libc.a(*) libm.a(*) libgcc.a(*) }
}
_boot_end = 0x08006000;
ASSERT(SIZEOF(.factory_init_request) == 28,
       "factory init request wire size mismatch")
ASSERT(_boot_code_end <= 0x08005800,
       "bootloader code overlaps factory init page")
