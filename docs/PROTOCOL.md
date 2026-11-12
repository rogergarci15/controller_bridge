# Protocolo BLE de Zwift Play ("ZAP", Zwift Accessory Protocol)

Estado: **investigación (Fase 0)**. Nada de esto está verificado todavía contra
mis mandos (firmware 1.2.0). Cada dato lleva su fuente y, donde las fuentes no
coinciden o no dicen nada, queda marcado como **⚠ POR VERIFICAR** con la forma
de comprobarlo en la Fase 1.

## Fuentes

| Sigla | Fuente | Licencia | Qué aporta |
|---|---|---|---|
| **[BC]** | `OpenBikeControl/bikecontrol` @ `341ad5c` (11-nov-2026), `lib/bluetooth/devices/zwift/*` y `prop_public/lib/protocol/zwift.pb*.dart` | Non-Commercial License v1.0 (GPL-3.0 hasta el tag `gpl3`) | Implementación viva, incluye firmware 2.x |
| **[AJ]** | `ajchellew/zwiftplay` (`README.md`, `zaplibrary/…`) | **Sin fichero de licencia** (todos los derechos reservados por defecto) | Ingeniería inversa original: UUIDs, handshake, cifrado |
| **[MK-P]** | Makinolo, *Connecting to Zwift Play controllers* (2023-10-08) | Artículo de blog | Detalle del cifrado y de los mensajes |
| **[MK-R]** | Makinolo, *Zwift Ride protocol* (2024-07-26, editado ene-2025) | Artículo de blog | Protocolo sin cifrar del Ride |
| **[JT]** | `jat255/zwift_click_handling` | MIT | Ejemplo en Python + bleak (Zwift Click) |

Los artículos de Makinolo se leyeron en versión texto: los volcados hex y los
bloques `.proto` de la página no se pudieron extraer, así que lo que cito de
ellos es solo lo que aparece en la prosa.

Los hechos del protocolo (UUIDs, bytes, números de campo) no son código
protegido; este documento los describe con palabras propias y no copia código
de ninguna fuente.

---

## 1. Anuncio BLE e identificación

| Dato | Valor | Fuente |
|---|---|---|
| Nombre anunciado | `Zwift Play` (ambos mandos) | [MK-P], [AJ] `GenericBleUuids` |
| Company ID (datos de fabricante) | `0x094A` = 2378 (Zwift, Inc.) | [BC] `constants.dart: ZWIFT_MANUFACTURER_ID`, [AJ] `ZapConstants`, [MK-P] |
| Carga de fabricante | 1 byte de tipo de dispositivo + 2 bytes de "dirección corta" (últimos 2 bytes de la MAC) | [MK-P] |
| Servicio anunciado | UUID propietario de 128 bits (ver §2) | [MK-P] |

Byte de tipo de dispositivo (primer byte de la carga de fabricante):

| Valor | Dispositivo | Fuente |
|---|---|---|
| `0x02` | Play derecho (RC1) | [BC] `RC1_RIGHT_SIDE`, [AJ], [MK-P] |
| `0x03` | Play izquierdo (RC1) | [BC] `RC1_LEFT_SIDE`, [AJ], [MK-P] |
| `0x0E` | Play con firmware 2.x (un solo dispositivo) | [BC] `RC1_FW2` |
| `0x07` / `0x08` | Ride derecho / izquierdo | [BC], [MK-R] |
| `0x09` | Click (BC1) | [BC], [AJ], [MK-P] |
| `0x0A` / `0x0B` | Click v2 derecho / izquierdo ("unconfirmed" según el propio [BC]) | [BC] |

**Así distingue BikeControl firmware 1.x de 2.x:** no mira la versión, mira
este byte en el anuncio (`bluetooth_device.dart: fromScanResult` →
`ZwiftDeviceType.fromManufacturerData`). `0x02`/`0x03` crea un `ZwiftPlay`
(protocolo clásico, un objeto por mando); `0x0E` crea un `ZwiftPlayFw2`, que es
una subclase de `ZwiftRide` (protocolo del Ride, una sola conexión). La cadena
de versión (característica `2A26`) solo la usa para avisos de "actualiza" o
"firmware más nuevo que el soportado".

⚠ POR VERIFICAR — En Windows, [BC] comenta que a veces el anuncio llega sin
datos de fabricante. `tools/scan.py` debe mostrar nombre, datos de fabricante y
UUIDs para ver qué llega de verdad con bleak/WinRT, y tener un plan B
(conectar y dejar que el campo 1 del mensaje de botones diga el lado, §6.1).

## 2. Servicios y características GATT

Servicios estándar: Generic Access `1800`, Device Information `180A`
(fabricante `2A29`, nº de serie `2A25`, hardware `2A27`, **firmware `2A26`**),
Battery `180F` (nivel `2A19`). Fuente: [AJ] `GenericBleUuids`, [MK-P].

Servicio propietario `00000001-19ca-4651-86e5-fa29dcdd09d1`
(fuente: [AJ] `ZapBleUuids`, sacado de descompilar Zwift Companion; [BC]
`ZWIFT_CUSTOM_SERVICE_UUID`; [MK-P]):

| UUID (`0000000X-19ca-4651-86e5-fa29dcdd09d1`) | Nombre | Propiedades | Uso |
|---|---|---|---|
| `…0002` | ASYNC ("measurement") | Notify | Eventos: botones, idle, batería |
| `…0003` | SYNC_RX ("control point") | Write, Write-No-Response | Lo que escribe la app: handshake, comandos |
| `…0004` | SYNC_TX ("command response") | Indicate, Read | Respuestas: handshake y respuestas a comandos |
| `…0006` | desconocida | Indicate, Read, Write, Write-No-Response | No usada por ninguna fuente ([AJ]: "not seen this characteristic used") |

> Corrección respecto al enunciado inicial: **SYNC_TX es `…0004`**, no `…0006`.
> Los nombres son desde el punto de vista del mando (RX = lo que recibe).

[BC] se suscribe a notificaciones en ASYNC y a indicaciones en SYNC_TX antes
de escribir el handshake (`zwift_device.dart: handleServices`).

En firmware 2.x el servicio puede aparecer como UUID de 16 bits `FC82`
(`0000fc82-0000-1000-8000-00805f9b34fb`); [BC] busca primero ese y luego el de
128 bits, con las mismas tres características. Fuente: [BC]
`ZWIFT_RIDE_CUSTOM_SERVICE_UUID`, [MK-R] (cambio de enero de 2025 en el Ride).

## 3. Handshake

Hay **dos modos**, y el mando elige según lo que se le escriba:

### 3.1 Modo sin cifrar (el que usa BikeControl)

1. Suscribirse a ASYNC (notify) y SYNC_TX (indicate).
2. Escribir en SYNC_RX los 6 bytes ASCII `RideOn` = `52 69 64 65 4f 6e`, sin
   nada más, *write without response*.
3. El mando responde por SYNC_TX con `RideOn` + 2 bytes.
4. A partir de ahí los mensajes llegan en claro: `[tipo][protobuf]`.

Fuentes: [BC] `zwift_device.dart: setupHandshake` (escribe solo `RIDE_ON`, y
`ZwiftPlay` no lo sobrescribe); [AJ] `AbstractZapDevice` (constante
`ENCRYPTED`, comentario "you can bypass all the crypto and just get the
protocol buffer data", y `buildHandshakeStart` que devuelve solo `RIDE_ON`
cuando no hay cifrado); [JT] (opción `encrypted=False`); [MK-R] (el Ride
directamente no cifra).

### 3.2 Modo cifrado (el de Zwift)

1. Generar un par de claves EC en la curva **secp256r1 / prime256v1 / NIST
   P-256**. Fuente: [AJ] `LocalKeyProvider`, [MK-P].
2. Escribir en SYNC_RX: `RideOn` + 2 bytes de cabecera + clave pública propia
   de **64 bytes** (X ‖ Y, 32 + 32, punto sin comprimir **sin** el prefijo
   `0x04`). Fuente: [AJ] `EncryptionUtils.publicKeyToByteArray`, [MK-P].
3. El mando responde por SYNC_TX: `RideOn` + 2 bytes + su clave pública de 64
   bytes en el mismo formato.

Los 2 bytes de cabecera **no coinciden entre fuentes**:

| Dirección | Valor | Fuente |
|---|---|---|
| app → mando | `01 02` | [MK-P]; captura HCI real en [AJ] `README.md` |
| app → mando | `00 09` | [AJ] `ZapConstants.REQUEST_START`, [BC] `REQUEST_START` |
| mando → app | `01 01` | captura HCI real en [AJ] `README.md` |
| mando → app | `00 09` (a veces `01 03`) | [MK-P] |
| mando → app | `01 03` | [AJ] `RESPONSE_START`, [BC] `RESPONSE_START_CLICK`, [JT] |
| mando → app | `01 04` | [BC] `RESPONSE_START_PLAY` (el que espera para el Play) |

[AJ] y [BC] comentan que "no parecen importar, solo hace falta que la cabecera
sea RideOn + 2 bytes". Probablemente codifican versión de protocolo/firmware.

⚠ POR VERIFICAR — Qué 2 bytes devuelve **mi** firmware 1.2.0. Diseño
consecuente: el parser **no** debe exigir un valor concreto; acepta cualquier
respuesta que empiece por `RideOn` y decide por longitud (8 bytes = sin clave;
8 + 64 = con clave). `tools/sniff.py` registrará la respuesta exacta.

## 4. Cifrado (solo en modo 3.2)

| Parámetro | Valor | Fuente |
|---|---|---|
| Acuerdo de clave | ECDH sobre P-256, clave privada propia × clave pública del mando | [AJ] `EncryptionUtils.generateSharedSecretBytes`, [MK-P] |
| KDF | HKDF con SHA-256 | [AJ] `generateHKDFBytes`, [MK-P] |
| Salt | clave pública **del mando** (64 B) ‖ clave pública **de la app** (64 B), en ese orden | [AJ] `ZapCrypto`, [MK-P] ("in that order") |
| Info | vacío (0 bytes) | [AJ] (`ByteArray(0)`); [MK-P] no lo menciona |
| Longitud de salida | 36 bytes | [AJ] `HKDF_LENGTH`, [MK-P] |
| Clave AES | bytes 0..31 (AES-256) | [AJ] `KEY_LENGTH`; [MK-P] ("aes-256-ccm") |
| Prefijo de nonce ("IV") | bytes 32..35 | [AJ] `ZapCrypto.initialise`; [MK-P] |
| Cifrado | AES-CCM | [AJ] `CCMBlockCipher`, [MK-P] |
| Nonce | 8 bytes = prefijo de 4 B ‖ contador de 4 B tal cual llega en el mensaje | [AJ] `decrypt`, [MK-P] |
| Tag (MIC) | 4 bytes, al final | [AJ] `MAC_LENGTH`, [MK-P] |
| AAD | ninguno | [AJ] (no se pasa); [MK-P] no lo menciona |

Trama cifrada: `contador (4 B) ‖ texto cifrado ‖ tag (4 B)`. El texto en claro
es `[tipo][protobuf]`, igual que en modo sin cifrar.

Contador: en las capturas de [AJ] `README.md` se ve **little-endian**
(`00 00 00 00`, `01 00 00 00`, … `95 04 00 00`) y [MK-P] dice lo mismo. Para
**descifrar** da igual, porque el nonce usa los 4 bytes recibidos sin
interpretarlos. Para **cifrar** (solo haría falta para enviar comandos, p. ej.
vibración) hay una discrepancia: el código de [AJ] serializa su contador en
big-endian. ⚠ POR VERIFICAR si alguna vez enviamos comandos cifrados; los
contadores de cada sentido son independientes y empiezan en 0 ([AJ] README).

Con `cryptography`: `AESCCM(key, tag_length=4).decrypt(nonce, ct_y_tag, None)`
(nonce de 8 bytes está dentro del rango 7–13 que admite CCM).

## 5. Formato de los mensajes (descifrados o en claro)

`[1 byte de tipo][cuerpo protobuf]`. El byte de tipo no es protobuf.

| Tipo | Nombre | Dirección | Fuente |
|---|---|---|---|
| `0x07` | Estado de botones del Play (`PlayKeyPadStatus`) | mando → app | [BC] `PLAY_NOTIFICATION_MESSAGE_TYPE`, [AJ], [MK-P] |
| `0x15` (21) | Idle / vacío, ~1 por segundo, sin cuerpo | mando → app | [BC] `EMPTY_MESSAGE_TYPE`, [AJ], [MK-P] |
| `0x19` (25) | Batería | mando → app | [BC] `BATTERY_LEVEL_TYPE`, [AJ] |
| `0x23` (35) | Estado de botones Ride / Play fw 2.x (`RideKeyPadStatus`) | mando → app | [BC] `Opcode.CONTROLLER_NOTIFICATION`, [MK-R] |
| `0x37` (55) | Estado de botones del Click | mando → app | [BC], [AJ] |
| `0x12` | Comando de vibración | app → mando | [BC] `VIBRATE_PATTERN`, [MK-P] |
| `0xFE` | Desconexión / pérdida de control (1 byte) | mando → app | [AJ] `DISCONNECT_MESSAGE_TYPE`, [BC] `Opcode.LOST_CONTROL` |

El mando repite el mismo estado varias veces; hay que deduplicar comparando con
el estado anterior ([BC] `handleButtonsClicked`, [AJ] `ZwiftPlay.kt`).

## 6. Botones y palancas

### 6.1 Firmware 1.x — mensaje `0x07`

Todos los campos son varint. Fuente de los números de campo: [BC]
`zwift.pb.dart: PlayKeyPadStatus`, [AJ] `ControllerNotification.kt`
(comentado "with 1.2.1 firmware"), [MK-P].

| Campo | Tipo | Significado |
|---|---|---|
| 1 | enum | Lado: `0` = mando **derecho**, `1` = izquierdo |
| 2 | enum | Derecho: **Y** · Izquierdo: **arriba** |
| 3 | enum | Derecho: **Z** · Izquierdo: **izquierda** |
| 4 | enum | Derecho: **A** · Izquierdo: **derecha** |
| 5 | enum | Derecho: **B** · Izquierdo: **abajo** |
| 6 | enum | Botón lateral / "shift" (ver aviso) |
| 7 | enum | Botón de encendido (ver aviso) |
| 8 | sint32 (zigzag) | Palanca naranja, eje principal (`Analog_LR`) |
| 9 | sint32 según [BC]; varint sin signo según [AJ] | Segundo valor analógico (`Analog_UD`) |

**Lógica invertida:** `0` = pulsado, `1` = suelto ([BC] `PlayButtonStatus.ON = 0`,
[AJ] `BTN_PRESSED = 0`, [MK-P]). Ojo: al ser proto con valor por defecto 0, un
campo **ausente** se leería como "pulsado"; el mando envía todos los campos
(mensaje de 19–21 bytes según [MK-P]), pero el parser debe tratar "ausente"
como "suelto" para no generar pulsaciones fantasma.

Palanca (campo 8): zigzag, rango **−100…+100**, 0 en reposo ([MK-P], [BC]).
[BC] solo considera la palanca "pulsada" cuando `abs(valor) == 100`, es decir
la trata como un botón más y **no distingue el signo**.

⚠ POR VERIFICAR con capturas etiquetadas (las fuentes no coinciden):

1. **Campos 6 y 7.** [BC] y [AJ]: 6 = lateral/shift, 7 = encendido.
   [MK-P] lo da al revés (6 = ON/OFF, 7 = shifter). Dos contra uno, pero se
   comprueba pulsando cada uno.
2. **Signo y eje de la palanca.** [AJ]: "en el izquierdo es negativo al girar
   y positivo al frenar, y al revés en el derecho" (todo en el campo 8).
   [MK-P]: campo 8 = empuje izquierda/derecha, campo 9 = fuerza de freno
   (0…200, sin signo). [BC] lo llama `Analog_LR` / `Analog_UD`. Hay que
   capturar: palanca hacia dentro, hacia fuera, y a medio recorrido, en cada
   mando.
3. **Granularidad.** Si el campo 8 da valores intermedios de forma continua (lo
   necesito para umbral + histéresis) o salta a ±100.

### 6.2 Firmware 2.x — mensaje `0x23` (solo referencia, no es mi caso)

Qué cambia en 2.x según [BC] (`zwift_play_fw2.dart`, `zwift_ride.dart`) y
[MK-R]:

- Un solo dispositivo BLE para los dos mandos (tipo `0x0E`); el derecho se
  enlaza con el izquierdo y todo sale por una conexión.
- Sin cifrado: handshake = `RideOn` a secas, respuesta `RideOn` + 2 bytes.
- Botones en un **mapa de bits** (campo 1, varint de 32 bits, lógica invertida:
  bit a 0 = pulsado) en vez de un campo por botón.
- Palancas en un campo repetido de submensajes `{1: posición (0 = izq.,
  1 = dcha.), 2: valor sint32 −100…100}`. [BC] usa umbral `abs ≥ 25`.
  Número de campo: 3 según [BC] `RideKeyPadStatus`; 2 según la prosa de
  [MK-R]. ⚠ discrepancia.
- Batería por opcode `0x19` (`BatteryNotification`), más opcodes de un
  protocolo "ZP" común (GET `0x00`, GET_RESPONSE `0x3C`, STATUS_RESPONSE
  `0x3E`, LOG_DATA `0x2A`, VENDOR_MESSAGE `0xFF`…).
- `ZwiftPlayFw2` **no** activa el "desbloqueo con Zwift" que sí necesitan Click
  v2 y Ride V2 (`usesZwiftUnlock` solo es cierto para un `ZwiftRide` puro con
  firmware ≥ 1.3.0).

Máscaras de bits — ⚠ las dos tablas que hay dentro del propio [BC] **no
coinciden** a partir de Z:

| Botón | `zwift_ride.dart` (la que usa el código) | `zwift.pbenum.dart` (stub) |
|---|---|---|
| LEFT / UP / RIGHT / DOWN | `0x1` / `0x2` / `0x4` / `0x8` | igual |
| A / B / Y | `0x10` / `0x20` / `0x40` | igual |
| Z | `0x80` | `0x100` |
| SHFT_UP_L / SHFT_DN_L | `0x100` / `0x200` | `0x200` / `0x400` |
| POWERUP_L / ONOFF_L | `0x400` / `0x800` | `0x800` / `0x1000` |
| SHFT_UP_R / SHFT_DN_R | `0x1000` / `0x2000` | `0x2000` / `0x4000` |
| POWERUP_R / ONOFF_R | `0x4000` / `0x8000` | `0x10000` / `0x20000` |

Si algún día actualizo a 2.x habrá que capturar antes de fiarse de ninguna.

## 7. Keep-alive

- **Mando → app:** mensaje idle `0x15` aproximadamente cada segundo, también
  mientras hay botones pulsados ([MK-P]). Sirve como latido: si dejan de llegar
  durante unos segundos, la conexión está muerta aunque el SO no lo haya
  notado.
- **App → mando:** [BC] **no envía nada** periódico a un Play real (su
  `ControllerKeepAlive` es para cuando *emula* un mando hacia Zwift por red, no
  para hablar con el mando). [MK-P] lista un comando `0x08` con parámetros
  `86 06` / `82 06` "enviado periódicamente" por Zwift, de función desconocida.

⚠ POR VERIFICAR — Dejar `sniff.py` conectado 10 minutos sin tocar nada y ver
si el mando corta la conexión o deja de notificar. Si aguanta, no enviamos
nada (lo más simple y lo que hace [BC]).

## 8. Batería

Dos vías:

1. **Estándar:** servicio `180F`, característica `2A19` (un byte, 0–100). La
   más simple y la que usaré para el aviso de batería baja. Fuente: [AJ], [JT].
2. **ZAP:** mensaje tipo `0x19` con el nivel en el **campo 2** (varint).
   Fuente: [AJ] `BatteryStatus.kt` ("tag starts at 2"); [BC] lee directamente
   el tercer byte del mensaje, que equivale a lo mismo.

## 9. Vibración (opcional)

Escribir en SYNC_RX: `12 12 08 0A 06 08 02 10 00 18` + 1 byte de patrón; [BC]
usa `0x20` para el aviso de cambio de marcha. Fuente: [BC] `VIBRATE_PATTERN` y
`_vibrate`; [MK-P] da la misma secuencia y habla de 123 patrones. En modo
cifrado habría que cifrarlo (ver aviso del contador en §4).

## 10. Restricciones de conexión

- Cada mando acepta **una sola central**: Zwift y Zwift Companion deben estar
  cerrados (y el mando "olvidado" si el SO lo retiene). Fuente: enunciado;
  coherente con el mensaje `0xFE` de [AJ] ("se ve cuando otro se conecta").
- En 1.x son **dos conexiones BLE** independientes, cada una con su handshake.
- No hace falta emparejar (bonding) a nivel de sistema: ninguna fuente lo hace;
  la seguridad es la capa de aplicación. ⚠ POR VERIFICAR en Windows 11.

## 11. Resumen de lo que hay que comprobar con el hardware (Fase 1)

| # | Pregunta | Cómo |
|---|---|---|
| 1 | ¿Llegan los datos de fabricante en Windows? | `scan.py` |
| 2 | ¿Qué UUID de servicio y qué características expone mi 1.2.0? | `scan.py` |
| 3 | ¿Responde al `RideOn` sin clave y manda protobuf en claro? ¿Con qué 2 bytes? | `sniff.py` |
| 4 | Campos 6 y 7: ¿cuál es el lateral y cuál el de encendido? | captura etiquetada |
| 5 | Palanca: signo, eje (campo 8 vs 9) y si es continua | captura etiquetada |
| 6 | ¿Aguanta la conexión sin keep-alive de la app? | captura de 10 min en reposo |
| 7 | ¿Con qué frecuencia notifica al pulsar? (para la latencia) | marcas de tiempo de la captura |
