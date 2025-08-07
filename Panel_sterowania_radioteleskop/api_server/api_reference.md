# API Reference — Sterownik Silnika Anteny Radioteleskopu

**Protokół komunikacji:** SPID  
**Autor:** Aleks Czarnecki

## Spis treści

1. [Czym jest to API](#czym-jest-to-api)
2. [REST API Endpoints](#rest-api-endpoints)
3. [Struktury danych](#struktury-danych)
4. [Połączenie z anteną](#połączenie-z-anteną)
5. [Sterowanie pozycją](#sterowanie-pozycją)
6. [Kalkulator astronomiczny](#kalkulator-astronomiczny)
7. [Śledzenie obiektów](#śledzenie-obiektów)
8. [Obsługa błędów](#obsługa-błędów)
9. [Przykłady użycia](#przykłady-użycia)

---

## Czym jest to API

To **REST API** do sterowania anteną radioteleskopu — serwer HTTP oferujący endpointy do kontroli sprzętu przez protokół SPID.

**Główne funkcje:**

- Połączenie z kontrolerem SPID przez port szeregowy
- Sterowanie pozycją anteny (azymut/elewacja)
- Obliczenia astronomiczne (pozycje Słońca, Księżyca, planet)
- Śledzenie obiektów niebieskich
- Interfejs webowy do sterowania
- System bezpieczeństwa z awaryjnym zatrzymaniem

**Architektura:**

```text
[Interfejs Web] ←→ [REST API] ←→ [Kontroler Anteny] ←→ [Sprzęt SPID]
```

---

## REST API Endpoints

### Status i informacje

- `GET /` - Informacje o API
- `GET /status` - Aktualny status systemu
- `GET /web_interface.html` - Interfejs webowy

### Połączenie

- `POST /connect` - Nawiąż połączenie z anteną
- `POST /disconnect` - Rozłącz z anteną
- `GET /ports` - Lista dostępnych portów szeregowych

### Sterowanie pozycją

- `GET /position` - Pobierz aktualną pozycję
- `POST /position` - Ustaw nową pozycję
- `POST /stop` - Zatrzymaj antenę

### Lokalizacja obserwatora

- `GET /observer` - Pobierz lokalizację obserwatora
- `POST /observer` - Ustaw lokalizację obserwatora

### Śledzenie astronomiczne

- `POST /track/{object_name}` - Rozpocznij śledzenie obiektu
- `POST /stop_tracking` - Zatrzymaj śledzenie

---

## Struktury danych

### PositionModel

```json
{
  "azimuth": 180.5,
  "elevation": 45.0
}
```

### ObserverLocationModel

```json
{
  "latitude": 50.0614,
  "longitude": 19.9372,
  "elevation": 220,
  "name": "Kraków"
}
```

### ConnectionConfigModel

```json
{
  "port": "/dev/ttyUSB0",
  "baudrate": 115200,
  "use_simulator": false
}
```

### StatusResponse

```json
{
  "connected": true,
  "current_position": {
    "azimuth": 180.5,
    "elevation": 45.0
  },
  "is_moving": false,
  "last_error": null,
  "observer_location": {
    "latitude": 50.0614,
    "longitude": 19.9372,
    "elevation": 220,
    "name": "Kraków"
  }
}
```

---

## Połączenie z anteną

### POST /connect

Nawiązuje połączenie z kontrolerem SPID.

**Parametry:**

```json
{
  "port": "/dev/ttyUSB0",
  "baudrate": 115200,
  "use_simulator": false
}
```

**Dodatkowe informacje:**

- `port`: Opcjonalnie, auto-detect — jeśli puste
- `baudrate`: Prędkość transmisji
- `use_simulator`: Ustaw na true dla symulatora

**Odpowiedź:**

```json
{
  "status": "connected",
  "port": "/dev/ttyUSB0",
  "simulator": false
}
```

### POST /disconnect

Rozłącza z anteną.

**Odpowiedź:**

```json
{
  "status": "disconnected"
}
```

---

## Sterowanie ruchem anteny

### GET /position

Pobiera aktualną pozycję anteny.

**Odpowiedź:**

```json
{
  "azimuth": 180.5,
  "elevation": 45.0
}
```

### POST /position

Ustawia nową pozycję anteny.

**Parametry:**

```json
{
  "azimuth": 180.0,
  "elevation": 45.0
}
```

**Odpowiedź:**

```json
{
  "status": "moving",
  "target": {
    "azimuth": 180.0,
    "elevation": 45.0
  }
}
```

### POST /stop

Natychmiast zatrzymuje antenę.

**Odpowiedź:**

```json
{
  "status": "stopped"
}
```

---

## Kalkulator astronomiczny

### POST /observer

Ustawia lokalizację obserwatora dla obliczeń astronomicznych.

**Parametry:**

```json
{
  "latitude": 50.0614,
  "longitude": 19.9372,
  "elevation": 220,
  "name": "Kraków"
}
```

### GET /observer

Pobiera aktualną lokalizację obserwatora.

---

## Śledzenie obiektów

### POST /track/{object_name}

Rozpoczyna śledzenie obiektu astronomicznego.

**URL:** `/track/Sun?object_type=SUN`

**Obsługiwane obiekty:**

- **SUN** — Słońce
- **MOON** — Księżyc
- **PLANET** — Planety (Mercury, Venus, Mars, Jupiter, Saturn)
- **STAR** — Gwiazdy

**Odpowiedź:**

```json
{
  "status": "tracking",
  "object": "Sun",
  "type": "SUN",
  "position": {
    "azimuth": 180.0,
    "elevation": 45.0
  }
}
```

### POST /stop_tracking

Zatrzymuje śledzenie obiektu.

**Odpowiedź:**

```json
{
  "status": "tracking_stopped"
}
```

---

## Obsługa błędów

API zwraca błędy w standardowym formacie:

```json
{
  "detail": "Opis błędu"
}
```

**Kody błędów:**

- `404` - Nie znaleziono (port, obiekt astronomiczny)
- `500` - Błąd serwera (problemy ze sprzętem)
- `503` - Usługa niedostępna (brak połączenia)

---

## Przykłady użycia

### Podstawowe sterowanie

```bash
# Połącz z symulatorem
curl -X POST http://localhost:8000/connect \
  -H "Content-Type: application/json" \
  -d '{"use_simulator": true}'

# Ustaw pozycję
curl -X POST http://localhost:8000/position \
  -H "Content-Type: application/json" \
  -d '{"azimuth": 180, "elevation": 45}'

# Sprawdź status
curl http://localhost:8000/status
```

### Śledzenie Słońca

```bash
# Ustaw lokalizację
curl -X POST http://localhost:8000/observer \
  -H "Content-Type: application/json" \
  -d '{"latitude": 50.0614, "longitude": 19.9372, "name": "Kraków"}'

# Rozpocznij śledzenie Słońca
curl -X POST "http://localhost:8000/track/Sun?object_type=SUN"
```

### Użycie interfejsu webowego

1. Uruchom API: `python api_server/start_server.py`
2. Otwórz: `http://localhost:8000/web_interface.html`
3. Kliknij "Tryb symulatora" i "Połącz"
4. Steruj anteną przez interfejs graficzny

---

## Uruchomienie API

### Instalacja zależności

```bash
cd api_server
pip install -r requirements.txt
```

### Uruchomienie serwera

```bash
# Sposób 1: Przez skrypt
python start_server.py

# Sposób 2: Bezpośrednio uvicorn
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Dostępne adresy:**

- API: `http://localhost:8000`
- Dokumentacja: `http://localhost:8000/docs`
- Interfejs webowy: `http://localhost:8000/web_interface.html`
