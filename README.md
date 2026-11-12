# Zwift Ride → MyWhoosh

Usa los mandos de la **Zwift Ride** en **MyWhoosh** (Windows): cambio de
marchas, dirección con las palancas y ratón con la cruceta para todo lo demás
(intensidad del entrenamiento, menús…).

La aplicación lee los mandos por Bluetooth y los convierte en teclas y
movimientos de ratón. Proyecto personal, sin relación con Zwift ni MyWhoosh.

## Para usarla (sin instalar nada)

1. Descarga `ZwiftRideBridge.exe` de la
   [última versión](https://github.com/rogergarci15/controller_bridge/releases/latest).
2. Ábrelo. La primera vez Windows mostrará «Windows protegió su PC» porque el
   programa no está firmado: pulsa **Más información → Ejecutar de todas formas**.
3. Enciende los mandos. Cuando la ventana diga **Conectado**, abre MyWhoosh.

Marca **Iniciar con Windows** si quieres que arranque sola: se queda
minimizada y se conecta en cuanto enciendes los mandos.

### Qué hace cada botón (por defecto)

| Mando | Acción en MyWhoosh |
|---|---|
| Botones de cambio derechos | Subir marcha (`K`) |
| Botones de cambio izquierdos | Bajar marcha (`I`) |
| Palanca izquierda / derecha | Girar a la izquierda / derecha (`A` / `D`) |
| Cruceta | Mover el puntero del ratón |
| `A` | Clic |
| `B` | `Enter` (pausa; repite el último botón pulsado con el ratón) |
| `Z` | Mostrar / ocultar la interfaz (`U`) |

Para cambiarlo: **Editar botones…** abre el fichero de configuración (con
todas las opciones explicadas dentro); guarda y pulsa **Aplicar cambios**.

### Requisitos y límites

- Windows 10/11 con Bluetooth.
- **Zwift Ride con firmware 1.2.0.** Los firmwares 1.3 y posteriores bloquean
  el uso fuera de Zwift. Zwift Play y Zwift Click no están soportados.
- Los botones solo actúan cuando **MyWhoosh es la ventana activa**.
- Los mandos aceptan una sola conexión: mientras la aplicación esté abierta,
  Zwift no podrá usarlos (y al revés). Cierra una para usar la otra.

### Problemas frecuentes

| Síntoma | Solución |
|---|---|
| Se queda en «Buscando los mandos…» | Enciende los mandos. Cierra Zwift y **Zwift Companion (también en el móvil)**. Comprueba que el Bluetooth del PC está activado |
| Conecta pero MyWhoosh no reacciona | Haz clic en la ventana de MyWhoosh. Si MyWhoosh se ejecuta como administrador, Windows bloquea las teclas |
| La marcha no cambia | Activa el cambio virtual en MyWhoosh; comprueba que `K` e `I` del teclado funcionan |
| «Reconectando…» a menudo | Batería baja o PC lejos de los mandos |
| El puntero va muy rápido o muy lento | Ajusta `mouse:` al final de la configuración |

## Para desarrollar

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

| Orden | Para qué |
|---|---|
| `python -m zwiftplay app` | La aplicación de escritorio |
| `python -m zwiftplay run` | El puente en consola (`--dry-run` no envía nada) |
| `python -m zwiftplay monitor` | Ver los eventos de los mandos |
| `python -m zwiftplay keytest k` | Enviar una tecla de prueba sin mandos |
| `python tools/scan.py` / `tools/sniff.py` | Diagnóstico y capturas BLE |

El ejecutable lo construye GitHub Actions (`.github/workflows/build.yml`) con
PyInstaller; al subir una etiqueta `v*` se publica como versión.

Documentación del protocolo: [`docs/PROTOCOL.md`](docs/PROTOCOL.md) y
[`docs/OPENBIKECONTROL.md`](docs/OPENBIKECONTROL.md).

## Licencia

MIT. Implementación propia a partir de documentación pública y de capturas
del hardware; no contiene código de BikeControl ni de otros proyectos.
