.syntax unified
.cpu cortex-m4
.thumb
.global Reset_Handler
.type Reset_Handler,%function
Reset_Handler:
    bl SystemInit
    ldr r0, =_sidata
    ldr r1, =_sdata
    ldr r2, =_edata
0:
    cmp r1, r2
    bcs 2f
    ldr r3, [r0], #4
    str r3, [r1], #4
    b 0b
2:
    ldr r1, =_sbss
    ldr r2, =_ebss
    movs r3, #0
3:
    cmp r1, r2
    bcs 4f
    str r3, [r1], #4
    b 3b
4:
    bl main
1:  b 1b
.size Reset_Handler, .-Reset_Handler
.section .isr_vector,"a",%progbits
.word 0x20006000
.word Reset_Handler
