1、功能说明

    1、SPI 读、写、擦除 GT25Q40

2、使用环境

    /* 硬件环境：工程对应的开发硬件平台 */
    开发板：N32L43XM-STB N32L40XM-STB V1.1

3、使用说明

    /* 描述相关模块配置方法；例如:时钟，I/O等 */
    1、SystemClock：64MHz
    2、SPI1: NSS--PD7、SCK--PD4、MISO--PD5、MOSI--PD6、WP--PD8、HD--PD12 (N32L406RDL7和N32L402RDL7内部Flash连接引脚)
       SPI2: NSS--PC6、SCK--PC7、MISO--PC8、MOSI--PC9、WP--PD8、HD--PD12 (N32L406CDL7内部Flash连接引脚)

    /* 描述Demo的测试步骤和现象 */
    1.编译后下载程序复位运行；
    2.通过 SPI 读取 GT25Q40 的 ID，然后写数据，再读出来，比较读写数据，查看 TransferStatus1 状态为 PASSED，然后擦除块，查看 TransferStatus2 状态为 PASSED，检查擦除块正常，
      然后GT25Q40进入和退出睡眠模式，查看 TransferStatus3 状态为 PASSED，检查读取ID正常。

4、注意事项
    如果芯片型号是N32L406RDL7，选择N32L406RDL7宏定义，如果芯片型号是N32L406CDL7，选择N32L406CDL7宏定义，如果芯片型号是N32L402RDL7，选择N32L402RDL7宏定义。



1. Function description

    1. SPI read, write, erase GT25Q40

2. Use environment

    /* Hardware environment: the development hardware platform corresponding to the project */
    Development board: N32L43XM-STB N32L40XM-STB V1.1

3. Instructions for use

    /* Describe related module configuration methods; for example: clock, I/O, etc. */
    1. SystemClock: 64MHz
    2. SPI1: NSS--PD7, SCK--PD4, MISO--PD5, MOSI--PD6, WP--PD8, HD--PD12 (internal Flash connection pins of N32L406RDL7 and N32L402RDL7)
       SPI2: NSS--PC6, SCK--PC7, MISO--PC8, MOSI--PC9, WP--PD8, HD--PD12 (internal Flash connection pins of N32L406CDL7)

    /* Describe the testing steps and phenomena of the Demo */
    After compiling, download the program and reset it to run;
    Read the ID of GT25Q40 through SPI, write data, and then read it out. Compare the read and write data, check that the TransferStatus1 status is PASSED, then erase the block, check that the TransferStatus2 status is PASSED, and verify that the erase block is normal.
    Then GT25Q40 enters and exits sleep mode, and the TransferStatus3 status is checked to be PASSED, and the read ID is checked to be normal.

4. Attention
    If the chip model is N32L406RDL7, select the N32L406RDL7 macro definition. 
    If the chip model is N32L406CDL7, select the N32L406CDL7 macro definition.
    If the chip model is N32L402RDL7, select the N32L402RDL7 macro definition. 