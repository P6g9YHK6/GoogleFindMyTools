// Per-build settings main.c pulls in via #include. Used as-is when building
// this tree directly by hand (VS Code/ESP-IDF - see ../README.md); edit the
// values below for that.
//
// The webui Firmware page (webui/firmware_build.py) never touches this
// checked-in file - it runs each build in its own throwaway copy of this
// tree and overwrites build_config.h there with the values entered on the
// page instead.
#pragma once

// The advertisement key / EID retrieved via the registration flow - see
// ../README.md. Change it to your own before building.
#define GFMT_EID_STRING "INSERT_YOUR_ADVERTISEMENT_KEY_HERE"

// BLE device name (GAP), any short human-readable label.
#define GFMT_DEVICE_NAME "GFMT Tracker"

// FMDN frame type (byte 7 of the advertisement): 0x41 = unwanted tracking
// protection mode indicated, 0x40 = not indicated. This only changes what
// the tracker *advertises* - this firmware doesn't implement the buzzer/
// motion-alert behavior either way.
#define GFMT_ADV_FRAME_TYPE 0x41

// Advertising interval, in 0.625ms units (BLE spec range 0x0020-0x4000,
// i.e. 20ms-10240ms). 0x0020 is fastest/most power-hungry - raise it to
// save power at the cost of slower discovery.
#define GFMT_ADV_INTERVAL_UNITS 0x0020

// TX power, ESP32 (Bluedroid) only - see esp_gap_ble_api.h's esp_power_level_t
// for the full set of ESP_PWR_LVL_* levels. Not applied on ESP32-C3 (NimBLE)
// yet.
#if defined(CONFIG_IDF_TARGET_ESP32)
#define GFMT_TX_POWER_LEVEL ESP_PWR_LVL_P9
#endif
