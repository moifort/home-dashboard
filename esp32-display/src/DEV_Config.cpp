#include "DEV_Config.h"

void DEV_Digital_Write(UWORD Pin, UBYTE Value) {
    digitalWrite(Pin, Value);
}

UBYTE DEV_Digital_Read(UWORD Pin) {
    return digitalRead(Pin);
}

/**
 * Bit-banged SPI write — MSB first.
 * We toggle CLK and DIN manually since this display uses a non-standard
 * dual chip-select arrangement that doesn't map well to hardware SPI.
 */
void DEV_SPI_WriteByte(UBYTE Value) {
    for (int i = 0; i < 8; i++) {
        digitalWrite(EPD_CLK_PIN, LOW);
        if (Value & 0x80) {
            digitalWrite(EPD_DIN_PIN, HIGH);
        } else {
            digitalWrite(EPD_DIN_PIN, LOW);
        }
        Value = (Value << 1);
        digitalWrite(EPD_CLK_PIN, HIGH);
    }
}

void DEV_SPI_Write_nByte(const UBYTE *pData, UDOUBLE Len) {
    for (UDOUBLE i = 0; i < Len; i++) {
        DEV_SPI_WriteByte(pData[i]);
    }
}

void DEV_Delay_ms(UDOUBLE xms) {
    delay(xms);
}

UBYTE DEV_Module_Init(void) {
    pinMode(EPD_RST_PIN, OUTPUT);
    pinMode(EPD_DC_PIN, OUTPUT);
    pinMode(EPD_CS_M_PIN, OUTPUT);
    pinMode(EPD_CS_S_PIN, OUTPUT);
    pinMode(EPD_BUSY_PIN, INPUT);
    pinMode(EPD_CLK_PIN, OUTPUT);
    pinMode(EPD_DIN_PIN, OUTPUT);

    // Chip selects idle high
    digitalWrite(EPD_CS_M_PIN, HIGH);
    digitalWrite(EPD_CS_S_PIN, HIGH);
    digitalWrite(EPD_CLK_PIN, LOW);

    Debug("DEV_Module_Init done");
    return 0;
}

void DEV_Module_Exit(void) {
    digitalWrite(EPD_RST_PIN, LOW);
    digitalWrite(EPD_DC_PIN, LOW);
    digitalWrite(EPD_CS_M_PIN, LOW);
    digitalWrite(EPD_CS_S_PIN, LOW);
    digitalWrite(EPD_CLK_PIN, LOW);
    digitalWrite(EPD_DIN_PIN, LOW);

    Debug("DEV_Module_Exit done");
}
