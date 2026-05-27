#ifndef __EPD_10in85g_H_
#define __EPD_10in85g_H_

#include "DEV_Config.h"

#define EPD_10in85g_WIDTH       1360/2
#define EPD_10in85g_HEIGHT      480

#define EPD_10in85g_BLACK   0x0
#define EPD_10in85g_WHITE   0x1
#define EPD_10in85g_YELLOW  0x2
#define EPD_10in85g_RED     0x3

void EPD_10in85g_Init(void);
void EPD_10in85g_Clear(UBYTE color);
void EPD_10in85g_Display(const UBYTE *Image);
void EPD_10in85g_Sleep(void);

#endif
