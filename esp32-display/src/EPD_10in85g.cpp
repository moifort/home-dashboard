#include "EPD_10in85g.h"

// ----- Internal helpers -----

/**
 * SendCommand to master panel only (CS_M low).
 */
static void SendCommand_0(UBYTE Reg) {
    DEV_Digital_Write(EPD_DC_PIN, 0);
    DEV_Digital_Write(EPD_CS_M_PIN, 0);
    DEV_Digital_Write(EPD_CS_S_PIN, 1);
    DEV_SPI_WriteByte(Reg);
    DEV_Digital_Write(EPD_CS_M_PIN, 1);
}

/**
 * SendCommand to slave panel only (CS_S low).
 */
static void SendCommand_1(UBYTE Reg) {
    DEV_Digital_Write(EPD_DC_PIN, 0);
    DEV_Digital_Write(EPD_CS_M_PIN, 1);
    DEV_Digital_Write(EPD_CS_S_PIN, 0);
    DEV_SPI_WriteByte(Reg);
    DEV_Digital_Write(EPD_CS_S_PIN, 1);
}

/**
 * SendCommand to both panels simultaneously.
 */
static void SendCommand_ALL(UBYTE Reg) {
    DEV_Digital_Write(EPD_DC_PIN, 0);
    DEV_Digital_Write(EPD_CS_M_PIN, 0);
    DEV_Digital_Write(EPD_CS_S_PIN, 0);
    DEV_SPI_WriteByte(Reg);
    DEV_Digital_Write(EPD_CS_M_PIN, 1);
    DEV_Digital_Write(EPD_CS_S_PIN, 1);
}

/**
 * SendData to master panel only.
 */
static void SendData_0(UBYTE Data) {
    DEV_Digital_Write(EPD_DC_PIN, 1);
    DEV_Digital_Write(EPD_CS_M_PIN, 0);
    DEV_Digital_Write(EPD_CS_S_PIN, 1);
    DEV_SPI_WriteByte(Data);
    DEV_Digital_Write(EPD_CS_M_PIN, 1);
}

/**
 * SendData to slave panel only.
 */
static void SendData_1(UBYTE Data) {
    DEV_Digital_Write(EPD_DC_PIN, 1);
    DEV_Digital_Write(EPD_CS_M_PIN, 1);
    DEV_Digital_Write(EPD_CS_S_PIN, 0);
    DEV_SPI_WriteByte(Data);
    DEV_Digital_Write(EPD_CS_S_PIN, 1);
}

/**
 * SendData to both panels simultaneously.
 */
static void SendData_ALL(UBYTE Data) {
    DEV_Digital_Write(EPD_DC_PIN, 1);
    DEV_Digital_Write(EPD_CS_M_PIN, 0);
    DEV_Digital_Write(EPD_CS_S_PIN, 0);
    DEV_SPI_WriteByte(Data);
    DEV_Digital_Write(EPD_CS_M_PIN, 1);
    DEV_Digital_Write(EPD_CS_S_PIN, 1);
}

/**
 * Wait until BUSY pin goes LOW (display ready).
 */
static void ReadBusy(void) {
    Debug("e-Paper busy");
    DEV_Delay_ms(100);
    while (DEV_Digital_Read(EPD_BUSY_PIN) == 1) {
        DEV_Delay_ms(100);
    }
    Debug("e-Paper busy release");
}

/**
 * Hardware reset sequence.
 */
static void Reset(void) {
    DEV_Digital_Write(EPD_RST_PIN, 1);
    DEV_Delay_ms(200);
    DEV_Digital_Write(EPD_RST_PIN, 0);
    DEV_Delay_ms(2);
    DEV_Digital_Write(EPD_RST_PIN, 1);
    DEV_Delay_ms(200);
}

/**
 * Turn on display — triggers the refresh cycle.
 */
static void TurnOnDisplay(void) {
    SendCommand_0(0x12);
    SendData_0(0x00);
    SendCommand_1(0x12);
    SendData_1(0x00);
    ReadBusy();
}

// ----- Public API -----

void EPD_10in85g_Init(void) {
    Reset();
    ReadBusy();

    // Command 0x00: Panel setting
    SendCommand_ALL(0x00);
    SendData_ALL(0x2F);
    SendData_ALL(0x69);

    // Command 0x01: Power setting
    SendCommand_ALL(0x01);
    SendData_ALL(0x37);
    SendData_ALL(0x00);
    SendData_ALL(0x23);
    SendData_ALL(0x23);

    // Command 0x03: Power off sequence
    SendCommand_ALL(0x03);
    SendData_ALL(0x00);

    // Command 0x06: Booster soft start
    SendCommand_ALL(0x06);
    SendData_ALL(0xC7);
    SendData_ALL(0xC7);
    SendData_ALL(0x1D);

    // Command 0x30: PLL control — frame rate
    SendCommand_ALL(0x30);
    SendData_ALL(0x39);

    // Command 0x41: Temperature sensor setting
    SendCommand_ALL(0x41);
    SendData_ALL(0x00);

    // Command 0x50: VCOM and data interval
    SendCommand_ALL(0x50);
    SendData_ALL(0x37);
    SendData_ALL(0x0D);

    // Command 0x60: TCON setting
    SendCommand_ALL(0x60);
    SendData_ALL(0x22);

    // Command 0x61: Resolution setting — per panel
    // Master panel
    SendCommand_0(0x61);
    SendData_0(0x02);   // Width high byte: 680 >> 8 = 2
    SendData_0(0xA8);   // Width low byte:  680 & 0xFF = 0xA8
    SendData_0(0x01);   // Height high byte: 480 >> 8 = 1
    SendData_0(0xE0);   // Height low byte:  480 & 0xFF = 0xE0

    // Slave panel
    SendCommand_1(0x61);
    SendData_1(0x02);
    SendData_1(0xA8);
    SendData_1(0x01);
    SendData_1(0xE0);

    // Command 0xE3: Power saving
    SendCommand_ALL(0xE3);
    SendData_ALL(0xAA);

    DEV_Delay_ms(100);

    // Command 0x50 again
    SendCommand_ALL(0x50);
    SendData_ALL(0x37);
    SendData_ALL(0x0D);

    Debug("EPD_10in85g_Init done");
}

void EPD_10in85g_Clear(UBYTE color) {
    UWORD Width = EPD_10in85g_WIDTH / 4;  // 680/4 = 170 bytes per row per panel
    UWORD Height = EPD_10in85g_HEIGHT;     // 480

    // Build the fill byte: 4 pixels per byte, 2 bits each
    UBYTE colorByte = (color << 6) | (color << 4) | (color << 2) | color;

    // Send data to master panel
    SendCommand_0(0x10);
    for (UWORD j = 0; j < Height; j++) {
        for (UWORD i = 0; i < Width; i++) {
            SendData_0(colorByte);
        }
    }

    // Send data to slave panel
    SendCommand_1(0x10);
    for (UWORD j = 0; j < Height; j++) {
        for (UWORD i = 0; i < Width; i++) {
            SendData_1(colorByte);
        }
    }

    TurnOnDisplay();
    Debug("EPD_10in85g_Clear done");
}

void EPD_10in85g_Display(const UBYTE *Image) {
    UWORD Width = EPD_10in85g_WIDTH / 4;  // 170 bytes per row per panel
    UWORD Height = EPD_10in85g_HEIGHT;     // 480

    // The image buffer is laid out as a single continuous buffer for the
    // full 1360x480 display at 2 bits/pixel = 1360/4 = 340 bytes per row.
    // Each row: first 170 bytes = master (left), next 170 bytes = slave (right).

    // Send to master panel (left half)
    SendCommand_0(0x10);
    for (UWORD j = 0; j < Height; j++) {
        for (UWORD i = 0; i < Width; i++) {
            SendData_0(Image[j * Width * 2 + i]);
        }
    }

    // Send to slave panel (right half)
    SendCommand_1(0x10);
    for (UWORD j = 0; j < Height; j++) {
        for (UWORD i = 0; i < Width; i++) {
            SendData_1(Image[j * Width * 2 + i + Width]);
        }
    }

    TurnOnDisplay();
    Debug("EPD_10in85g_Display done");
}

void EPD_10in85g_Sleep(void) {
    SendCommand_ALL(0x02);  // Power off
    ReadBusy();
    SendCommand_ALL(0x07);  // Deep sleep
    SendData_ALL(0xA5);     // Check code
    Debug("EPD_10in85g_Sleep done");
}
