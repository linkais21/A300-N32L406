1、功能说明
    USB HID 设备

2、使用环境
    硬件环境：工程对应的开发硬件平台 
    开发板：   N32G4XV-STB V1.1


3、使用说明
    描述相关模块配置方法；例如:时钟，I/O等 
         1. SystemClock：144MHz
         2. USBClock: 48MHz
         3. GPIO:KEY1 -- PA4
                 LED1 -- PA4
                 LED2 -- PB4
                 LED3 -- PA5

    描述Demo的测试步骤和现象 
         1. 编译后下载程序复位运行；
         2. 通过 USB 线连接 J3 USB 口，电脑识别出HID设备;
         3. 点击按键KEY1， HID设备会通过IN端点发出按键信息
         4. 在PC端通过OUT端点向设备发送数据可以控制LED1~LED3的状态
            发送 0x01 0x00 LED1灭
            发送 0x01 0x01 LED1点亮
            发送 0x02 0x00 LED2灭
            发送 0x02 0x01 LED2点亮
            发送 0x03 0x00 LED3灭
            发送 0x03 0x01 LED3点亮

4、注意事项
    无

1. Function description
    USB HID device

2. Use environment
    Hardware environment: development hardware platform corresponding to the project 
    Development board:      N32G4XV-STB V1.1

3. Instructions for use
    Describe the configuration method of related modules; for example: clock, I/O, etc. 
        1. SystemClock: 144MHz
        2. USBClock: 48MHz
        3. GPIO:KEY1 -- PA4
                LED1 -- PA4
                LED2 -- PB4
                LED3 -- PA5
    
    Describe the testing steps and phenomena of the Demo

        1. Download the program after compiling and reset it to run;
        2. Connect the J3 USB port via a USB cable, and the computer recognizes the HID device.
        3. When click the button KEY1, the HID device will send a key message through the IN endpoint.
        4. Control the status of LED1 to LED3 by sending data to the device through the OUT endpoint on the PC
           Send 0x01 0x00 LED1 Off
           Send 0x01 0x01 LED1 Light
           Send 0x02 0x00 LED2 off
           Send 0x02 0x01 LED2 Light
           Send 0x03 0x00 LED3 off
           Send 0x03 0x01 LED3 to light up
 
4. Attention
    None.