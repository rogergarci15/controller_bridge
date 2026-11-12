# OpenBikeControl (OBC) como salida hacia MyWhoosh

Estado: **investigación (Fase 0)**. Resumen de la especificación pública y de
cómo la usa BikeControl con MyWhoosh. Nada probado todavía contra MyWhoosh.

## Fuentes

| Sigla | Fuente | Licencia |
|---|---|---|
| **[SPEC]** | `OpenBikeControl/openbikecontrol-protocol`: `PROTOCOL.md`, `MDNS.md`, `BLE.md`, `examples/python/*` (espejo en openbikecontrol.org, revisión "2026-10") | **MIT** (fichero `LICENSE`, "OpenBikeControl Protocol Contributors") |
| **[BC]** | `OpenBikeControl/bikecontrol` @ `341ad5c`: `lib/bluetooth/devices/openbikecontrol/*`, `lib/utils/keymap/apps/my_whoosh.dart`, `CHANGELOG.md` | Non-Commercial License v1.0 |

## ¿Es abierto y está documentado?

**Sí.** La especificación está publicada, es de implementación libre y sin
tasas, bajo MIT, e incluye ejemplos en Python (también MIT) de los dos lados:
`mock_device_tcp.py` (el papel que haría mi app) y `tcp_trainer_app.py` /
`mdns_trainer_app.py` (el papel de MyWhoosh), más `protocol_parser.py` y
tests. La gestiona OpenBikeControl UG, la misma entidad que publica
BikeControl. Al ser MIT, puedo reutilizar esos ejemplos con atribución sin que
mi proyecto herede la licencia no comercial de BikeControl.

## Quién descubre a quién

Al revés de lo que uno esperaría: **mi app es el servidor**.

- El **mando** (o la app puente, o sea yo) anuncia por mDNS el servicio
  `_openbikecontrol._tcp.local.` y abre un **servidor TCP**.
- La **app de entrenamiento** (MyWhoosh) lo descubre, lee IP y puerto del
  registro SRV y **se conecta como cliente TCP**.

Fuente: [SPEC] `MDNS.md` ("Advertise … service", "Implement TCP server" en el
lado del dispositivo; "discover …", "Connect to `<device-ip>:<port>`" en el
lado de la app).

En MyWhoosh hay que activarlo a mano: pantalla de conexión → icono de
OpenBikeControl arriba a la derecha (fuente: [BC] `CHANGELOG.md`, entrada
5.2.0 del 06-04-2026).

## Anuncio mDNS

| Dato | Valor | Fuente |
|---|---|---|
| Tipo de servicio | `_openbikecontrol._tcp.local.` | [SPEC] `MDNS.md` |
| Puerto | **No normativo**: "configured port"; el ejemplo usa 8080. BikeControl prefiere **36867** y, si está ocupado, usa el siguiente libre y anuncia el real | [SPEC]; [BC] `OpenBikeControlConstants.TCP_PORT` |
| TXT `version` | `1` | [SPEC] |
| TXT `id` | identificador único (MAC o nº de serie); BikeControl envía `1337` | [SPEC]; [BC] `obc_mdns_emulator.dart` |
| TXT `name` | nombre del dispositivo | [SPEC] |
| TXT `service-uuids` | `d273f680-d548-419d-b9d1-fa0472345229` | [SPEC]; [BC] |
| TXT `manufacturer`, `model` | texto libre | [SPEC] |

⚠ POR VERIFICAR — Si MyWhoosh lista cualquier anuncio
`_openbikecontrol._tcp` o filtra por nombre de instancia/`manufacturer`
(BikeControl se anuncia como instancia `BikeControl`, manufacturer
`OpenBikeControl`). La especificación no impone nada, pero MyWhoosh es
código cerrado. Se comprueba anunciando con mi propio nombre y mirando si
aparece en su pantalla de conexión.

## Mensajes

Binario, igual en TCP y en BLE. Primer byte = tipo. No hay prefijo de
longitud ni campos multibyte (no aplica orden de bytes). Fuente: [SPEC]
`PROTOCOL.md`, `MDNS.md`.

| Tipo | Dirección | Formato |
|---|---|---|
| `0x01` Estado de botones | yo → MyWhoosh | `01` + pares `[id][estado]` (1 o más) |
| `0x02` Estado del dispositivo (solo TCP) | yo → MyWhoosh | `02 [batería 0–100 o FF] [conectado 00/01]`, cada 30–60 s o al cambiar |
| `0x03` Vibración | MyWhoosh → yo | `03 [patrón] [duración ×10 ms] [intensidad]` (4 bytes fijos) |
| `0x04` Info de la app | MyWhoosh → yo | `04 [versión=01] [lenId][id…] [lenVer][ver…] [n][ids de botón…]` |

Estado: `00` = suelto, `01` = pulsado, `02…FF` = analógico (con reglas
propias por botón).

⚠ Ambigüedad de la especificación: un `0x01` es de longitud variable y **no
tiene campo de longitud**; en TCP el final del mensaje no está definido. Como
emisor lo esquivo enviando **un mensaje por escritura** con un solo par (3
bytes) y `TCP_NODELAY`. Como receptor solo me llegan `0x03` (4 bytes fijos) y
`0x04` (autodelimitado por sus longitudes), así que no me afecta.

### IDs de botón que me interesan

| ID | Acción | Semántica |
|---|---|---|
| `0x01` | Subir marcha | pulsar / soltar |
| `0x02` | Bajar marcha | pulsar / soltar |
| `0x18` | Girar a la izquierda | mantener mientras dure |
| `0x19` | Girar a la derecha | mantener mientras dure |
| `0x1B` | Ángulo de dirección (analógico) | `(valor − 0x80) × 0,5°`, ±63°, máx. 30 envíos/s; `0x80` = centro, `0x00` = no disponible |
| `0x10`–`0x17` | Arriba, abajo, izquierda, derecha, seleccionar, atrás, menú, inicio | navegación |
| `0x40` | Cambiar cámara | `01` = siguiente |

Fuente: [SPEC] `PROTOCOL.md` (tabla completa allí: también freno `0x1A`,
power-ups `0x50`–`0x52`, entrenamiento `0x30`–`0x3C`…).

**Qué acepta MyWhoosh** según la lista por defecto de BikeControl ([BC]
`my_whoosh.dart: defaultObpSupportedButtons`): `0x01`, `0x02`, `0x03` (fijar
marcha), `0x10`–`0x17`, `0x18`, `0x19`, `0x40`. **No** incluye el ángulo
analógico `0x1B`, así que la dirección sería digital (izquierda/derecha
mantenido), igual que con teclado. La lista real la manda MyWhoosh en su
mensaje `0x04` al conectar; la registraré en el log.

## Viabilidad para este proyecto

| | Teclado (`pynput`) | OpenBikeControl por red |
|---|---|---|
| MyWhoosh necesita el foco | **Sí** | **No** |
| Riesgo de teclear en otra ventana | Sí | No |
| Dependencias | `pynput` | `zeroconf` (Python puro) |
| Permisos en Windows | Ninguno | Abrir un puerto TCP de escucha + mDNS (UDP 5353). ⚠ La primera vez Windows Defender Firewall puede pedir permiso para Python; **permitirlo requiere administrador** si se quiere tráfico desde otra máquina. Con MyWhoosh en el mismo PC puede no hacer falta. POR VERIFICAR |
| Configuración en MyWhoosh | Ninguna | Activar OpenBikeControl en la pantalla de conexión |
| Vibración al cambiar | No | Posible: MyWhoosh envía `0x03` y lo traduzco al comando de vibración del mando |
| Documentado | Atajos de MyWhoosh | Sí, MIT |

**Conclusión: viable y abierto.** Propongo mantener el teclado como backend
por defecto (cero configuración, es lo que pide el enunciado) y añadir OBC
como backend opcional en la Fase 3, porque elimina el problema del foco.

### Dos cosas que no he podido confirmar

1. **Versión de MyWhoosh.** El enunciado dice "desde la 5.7". Las fuentes no
   dan versión de MyWhoosh; el único dato fechado es el changelog de
   *BikeControl* 5.2.0 (06-04-2026), que anuncia la integración oficial.
   Puede que "5.x" sea la versión de BikeControl y no la de MyWhoosh.
2. **Variante de transporte.** BikeControl tiene dos variantes de red: mDNS +
   TCP (`_openbikecontrol._tcp`) y una sobre Direct Connect de Wahoo
   (`_wahoo-fitness-tnp._tcp`). Para MyWhoosh declara `obpMdns` ([BC]
   `my_whoosh.dart: connections`), es decir, la primera, que es la
   documentada.

### Lo que **no** voy a usar

"MyWhoosh Link": el método anterior de BikeControl (servidor TCP en el puerto
fijo 21587 haciéndose pasar por la app MyWhoosh Link, con mensajes JSON).
Es un protocolo propietario sin documentar, [BC] lo marca como obsoleto desde
5.2.0, y la única fuente sería código bajo licencia no comercial.

## Nota sobre el teclado (afecta al mapeo por defecto)

El mapa de teclas de MyWhoosh en BikeControl ([BC] `my_whoosh.dart`) asigna
**`I` → bajar marcha** y **`K` → subir marcha**, es decir, al revés de lo que
dice el enunciado ("subir / bajar → `I` / `K`"). Dirección: `A` izquierda,
`D` derecha, mantenidas (también flechas izquierda/derecha); `H` oculta la
interfaz; `1`–`7` son gestos. ⚠ POR VERIFICAR contigo en MyWhoosh antes de
fijar el `config.yaml` por defecto: pulsa `I` y dime si la marcha sube o baja.
