#ifndef __DEV_CONFIG_H_
#define __DEV_CONFIG_H_

#include <Arduino.h>
#include "config.h"

// ----- Type definitions -----
typedef uint8_t  UBYTE;
typedef uint16_t UWORD;
typedef uint32_t UDOUBLE;

// ----- Pin macros -----
#define EPD_RST_PIN     PIN_RST
#define EPD_DC_PIN      PIN_DC
#define EPD_CS_M_PIN    PIN_CS_M
#define EPD_CS_S_PIN    PIN_CS_S
#define EPD_BUSY_PIN    PIN_BUSY
#define EPD_CLK_PIN     PIN_CLK
#define EPD_DIN_PIN     PIN_DIN

// ----- Debug macro -----
#define DEBUG 1
#if DEBUG
#define Debug(__info, ...) Serial.printf("Debug: " __info "\r\n", ##__VA_ARGS__)
#else
#define Debug(__info, ...)
#endif

// ----- GPIO functions -----
void DEV_Digital_Write(UWORD Pin, UBYTE Value);
UBYTE DEV_Digital_Read(UWORD Pin);

// ----- SPI functions (bit-banged) -----
void DEV_SPI_WriteByte(UBYTE Value);
void DEV_SPI_Write_nByte(const UBYTE *pData, UDOUBLE Len);

// ----- Delay -----
void DEV_Delay_ms(UDOUBLE xms);

// ----- Module init/exit -----
UBYTE DEV_Module_Init(void);
void DEV_Module_Exit(void);

#endif
