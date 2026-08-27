#include "spi_flash.h"
#include "config.h"
#include "hw_init.h"
#include "n32l40x.h"
#define CMD_READ_ID 0x9F
#define CMD_READ 0x03
#define CMD_WRITE_ENABLE 0x06
#define CMD_PAGE_PROGRAM 0x02
#define CMD_SECTOR_ERASE 0x20
#define CMD_CHIP_ERASE 0xC7
#define CMD_READ_SR 0x05
#define SR_WIP 0x01
#define SR_WEL 0x02
static bool id_checked,id_valid;
static bool xfer(uint8_t t,uint8_t*r){uint32_t s=TICK_MS(),g=SPI_FLASH_TIMEOUT_MS*1024U+1U;while(SPI_I2S_GetStatus(FLASH_SPI,SPI_I2S_TE_FLAG)==RESET)if((uint32_t)(TICK_MS()-s)>=SPI_FLASH_TIMEOUT_MS||g--==0)return false;SPI_I2S_TransmitData(FLASH_SPI,t);s=TICK_MS();g=SPI_FLASH_TIMEOUT_MS*1024U+1U;while(SPI_I2S_GetStatus(FLASH_SPI,SPI_I2S_RNE_FLAG)==RESET)if((uint32_t)(TICK_MS()-s)>=SPI_FLASH_TIMEOUT_MS||g--==0)return false;*r=(uint8_t)SPI_I2S_ReceiveData(FLASH_SPI);return true;}
static uint32_t raw_id(void){uint8_t d,m,t,c;FLASH_CS_LOW();bool ok=xfer(CMD_READ_ID,&d)&&xfer(0xFF,&m)&&xfer(0xFF,&t)&&xfer(0xFF,&c);FLASH_CS_HIGH();return ok?((uint32_t)m<<16)|((uint32_t)t<<8)|c:0;}
static bool ensure_id(void){if(!id_checked){id_valid=raw_id()==0x684015UL;id_checked=true;}return id_valid;}
static bool status(uint8_t*s){uint8_t d;FLASH_CS_LOW();bool ok=xfer(CMD_READ_SR,&d)&&xfer(0xFF,s);FLASH_CS_HIGH();return ok;}
static bool ready(uint32_t to){uint32_t st=TICK_MS(),g=to*1024U+1U;uint8_t s;do{if(!status(&s))return false;if(!(s&SR_WIP))return true;}while((uint32_t)(TICK_MS()-st)<to&&g--);return false;}
static bool we(void){uint8_t d;FLASH_CS_LOW();bool ok=xfer(CMD_WRITE_ENABLE,&d);FLASH_CS_HIGH();return ok&&status(&d)&&(d&SR_WEL);}
void spi_flash_init(void){id_checked=false;(void)ensure_id();}
uint16_t spi_flash_read_id(void){uint32_t id=raw_id();id_checked=true;id_valid=id==0x684015UL;return (uint16_t)(id>>8);}
bool spi_flash_read(uint32_t a,uint8_t*b,uint32_t n){if(!b||a>FLASH_TOTAL_SIZE||n>FLASH_TOTAL_SIZE-a||!ensure_id())return false;uint8_t d;FLASH_CS_LOW();bool ok=xfer(CMD_READ,&d)&&xfer((uint8_t)(a>>16),&d)&&xfer((uint8_t)(a>>8),&d)&&xfer((uint8_t)a,&d);for(uint32_t i=0;ok&&i<n;i++)ok=xfer(0xFF,&b[i]);FLASH_CS_HIGH();return ok;}
bool spi_flash_erase_sector(uint32_t a){if(a>=FLASH_TOTAL_SIZE||a%FLASH_SECTOR_SIZE||!ensure_id()||!we())return false;uint8_t d;FLASH_CS_LOW();bool ok=xfer(CMD_SECTOR_ERASE,&d)&&xfer((uint8_t)(a>>16),&d)&&xfer((uint8_t)(a>>8),&d)&&xfer((uint8_t)a,&d);FLASH_CS_HIGH();return ok&&ready(SPI_FLASH_ERASE_TIMEOUT_MS);}
bool spi_flash_write(uint32_t a,const uint8_t*b,uint32_t n){if(!b||a>FLASH_TOTAL_SIZE||n>FLASH_TOTAL_SIZE-a||!ensure_id())return false;while(n){uint32_t k=FLASH_PAGE_SIZE-a%FLASH_PAGE_SIZE;if(k>n)k=n;if(!we())return false;uint8_t d;FLASH_CS_LOW();bool ok=xfer(CMD_PAGE_PROGRAM,&d)&&xfer((uint8_t)(a>>16),&d)&&xfer((uint8_t)(a>>8),&d)&&xfer((uint8_t)a,&d);for(uint32_t i=0;ok&&i<k;i++)ok=xfer(b[i],&d);FLASH_CS_HIGH();if(!ok||!ready(SPI_FLASH_TIMEOUT_MS))return false;a+=k;b+=k;n-=k;}return true;}
bool spi_flash_erase_chip(void){if(!ensure_id()||!we())return false;uint8_t d;FLASH_CS_LOW();bool ok=xfer(CMD_CHIP_ERASE,&d);FLASH_CS_HIGH();return ok&&ready(SPI_FLASH_ERASE_TIMEOUT_MS);}
