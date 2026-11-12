# zwiftplay-bridge

Puente Zwift Play → MyWhoosh: lee los mandos por Bluetooth LE y los traduce a
pulsaciones de teclado (y, más adelante, a OpenBikeControl por red).

**Estado: Fase 2 (protocolo y monitor).** Todavía no envía teclas.
Probado con Zwift Ride, firmware 1.2.0.
Documentación del protocolo en [`docs/PROTOCOL.md`](docs/PROTOCOL.md) y
[`docs/OPENBIKECONTROL.md`](docs/OPENBIKECONTROL.md).

## Instalación (Windows 11, sin administrador)

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

## Herramientas de diagnóstico

Antes de nada: **cierra Zwift y Zwift Companion** (también en el móvil) y
enciende los dos mandos. Cada mando acepta una sola conexión.

```powershell
python tools/scan.py                                  # qué se ve y qué servicios expone
python tools/sniff.py                                 # guion guiado de pulsaciones
python tools/sniff.py --mode idle --duration 600      # 10 min sin tocar nada
python tools/sniff.py --mode free -v                  # captura libre, mensajes en pantalla
python tools/sniff.py --handshake keyed               # mismo guion, con handshake cifrado
```

Las capturas se guardan en `captures/*.jsonl` (una línea JSON por mensaje,
con marca de tiempo, característica y bytes en hex).

## Ver los eventos en tiempo real

```powershell
python -m zwiftplay monitor                                              # con los mandos
python -m zwiftplay monitor --replay tests/fixtures/ride_fw120_guided.jsonl  # sin hardware
```

## Licencia

MIT. Implementación propia a partir de documentación pública; no contiene
código de BikeControl ni de otros proyectos. Fuentes en `docs/PROTOCOL.md`.
