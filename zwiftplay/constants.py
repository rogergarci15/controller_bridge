"""Constantes del protocolo BLE de Zwift Play.

Ninguna está inventada: cada una lleva su fuente. Siglas (ver docs/PROTOCOL.md):
  [BC]   OpenBikeControl/bikecontrol @ 341ad5c, lib/bluetooth/devices/zwift/
  [AJ]   ajchellew/zwiftplay, zaplibrary/src/main/java/com/che/zap/
  [MK-P] makinolo.com, "Connecting to Zwift Play controllers" (2023-10-08)
  [MK-R] makinolo.com, "Zwift Ride protocol" (2024-07-26)
"""

# --- Servicio propietario -------------------------------------------------
# [AJ] device/common/ZapBleUuids.kt; [BC] constants.dart; [MK-P]
ZWIFT_SERVICE_UUID = "00000001-19ca-4651-86e5-fa29dcdd09d1"
# Firmware 2.x / Ride: mismo servicio con UUID de 16 bits FC82.
# [BC] constants.dart ZWIFT_RIDE_CUSTOM_SERVICE_UUID; [MK-R] (edición ene-2025)
ZWIFT_SERVICE_UUID_FC82 = "0000fc82-0000-1000-8000-00805f9b34fb"
ZWIFT_SERVICE_UUIDS = (ZWIFT_SERVICE_UUID, ZWIFT_SERVICE_UUID_FC82)

# [AJ] ZapBleUuids.kt; [BC] constants.dart. Nombres desde el punto de vista
# del mando: RX = lo que recibe (escribimos nosotros), TX = lo que transmite.
ASYNC_CHAR_UUID = "00000002-19ca-4651-86e5-fa29dcdd09d1"  # notify
SYNC_RX_CHAR_UUID = "00000003-19ca-4651-86e5-fa29dcdd09d1"  # write
SYNC_TX_CHAR_UUID = "00000004-19ca-4651-86e5-fa29dcdd09d1"  # indicate, read
# [AJ] ZapBleUuids.kt: "I have not seen this characteristic used".
UNKNOWN6_CHAR_UUID = "00000006-19ca-4651-86e5-fa29dcdd09d1"

# --- Servicios estándar de Bluetooth SIG ----------------------------------
# Números asignados por Bluetooth SIG; presentes en el mando según [AJ]
# device/common/ZapBleUuids.kt (GenericBleUuids) y [MK-P].
FIRMWARE_REVISION_CHAR_UUID = "00002a26-0000-1000-8000-00805f9b34fb"
HARDWARE_REVISION_CHAR_UUID = "00002a27-0000-1000-8000-00805f9b34fb"
SERIAL_NUMBER_CHAR_UUID = "00002a25-0000-1000-8000-00805f9b34fb"
MANUFACTURER_NAME_CHAR_UUID = "00002a29-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_CHAR_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

# --- Anuncio --------------------------------------------------------------
# [BC] constants.dart ZWIFT_MANUFACTURER_ID; [AJ] ZapConstants.kt; [MK-P]
ZWIFT_COMPANY_ID = 0x094A

# Primer byte de los datos de fabricante -> tipo de dispositivo.
# 0x02/0x03/0x09: [AJ] ZapConstants.kt, [BC], [MK-P]. 0x07/0x08: [BC], [MK-R].
# 0x0E: [BC] RC1_FW2. 0x0A/0x0B: [BC] (marcados allí como "unconfirmed").
DEVICE_TYPES = {
    0x02: "play_right",
    0x03: "play_left",
    0x07: "ride_right",
    0x08: "ride_left",
    0x09: "click",
    0x0A: "click_v2_right",
    0x0B: "click_v2_left",
    0x0E: "play_fw2",
}

# --- Handshake ------------------------------------------------------------
# ASCII "RideOn". [AJ] ZapConstants.kt RIDE_ON; [BC] constants.dart; [MK-P]
RIDE_ON = bytes([0x52, 0x69, 0x64, 0x65, 0x4F, 0x6E])
# Los 2 bytes que siguen a "RideOn" en el handshake CON clave (app -> mando).
# Las fuentes no coinciden (docs/PROTOCOL.md §3.2):
#   01 02 -> [MK-P] y captura HCI real en el README de [AJ]
#   00 09 -> [AJ] ZapConstants.REQUEST_START, [BC] REQUEST_START
# Se usa por defecto el valor visto en una captura real; es configurable.
KEYED_REQUEST_HEADER_CAPTURED = bytes([0x01, 0x02])
KEYED_REQUEST_HEADER_CODE = bytes([0x00, 0x09])
# Longitud de la clave pública en el handshake: X || Y de P-256 sin el
# prefijo 0x04. [AJ] crypto/EncryptionUtils.kt; [MK-P]
PUBLIC_KEY_LENGTH = 64

# --- Tipos de mensaje (primer byte, tras descifrar si procede) -------------
# [BC] constants.dart; [AJ] ZapConstants.kt; [MK-P]
MSG_PLAY_KEYPAD = 0x07
MSG_IDLE = 0x15
MSG_BATTERY = 0x19
MSG_RIDE_KEYPAD = 0x23  # firmware 2.x / Ride. [BC] Opcode.CONTROLLER_NOTIFICATION
MSG_DISCONNECT = 0xFE  # [AJ] DISCONNECT_MESSAGE_TYPE; [BC] Opcode.LOST_CONTROL
