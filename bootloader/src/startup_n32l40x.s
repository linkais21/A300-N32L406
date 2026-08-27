.syntax unified
.cpu cortex-m4
.thumb
.global Reset_Handler
.type Reset_Handler,%function
Reset_Handler:
    bl main
1:  b 1b
.size Reset_Handler, .-Reset_Handler
.section .isr_vector,"a",%progbits
.word 0x20006000
.word Reset_Handler
