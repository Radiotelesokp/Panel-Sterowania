# SDR 

Program do włączania zasilania Bias-Tee, skanowania częstotliwości i rysowania wykresów sygnału z urządzenia SDR.

## Wymagania

- Python
- SoapySDR (instalowany systemowo)
- Urządzenie SDR wspierane przez SoapySDR

## Instalacja krok po kroku

### 1. Zainstaluj SoapySDR systemowo

```
sudo apt update
sudo apt install python3-soapysdr soapysdr-module-all
```

### 2. Utwórz środowisko wirtualne z dostępem do SoapySDR

```
python3 -m venv venv --system-site-packages
source venv/bin/activate
```

> Użycie `--system-site-packages` umożliwia dostęp do SoapySDR zainstalowanego przez `apt`.

### 3. Zainstaluj zależności Pythona

```
pip install -r requirements.txt
```

### 4. Uruchom program

```
python3 run_sdr.py
```

## Działanie

### Struktura:

1. **`run_sdr.py`** – Główny program sterujący:
   - Obsługuje komendy wpisywane przez użytkownika (np. `bias on`, `scan`, `exit`).
   - Inicjalizuje połączenie z urządzeniem SDR.
   - Wywołuje funkcje z innych modułów.

2. **`bias_tee.py`** – Obsługuje funkcje włączania, wyłączania i sprawdzania stanu zasilania Bias-Tee.

3. **`sdr_scan.py`** – Skanuje wybrane pasmo:
   - Dla każdego kroku częstotliwości pobiera próbki (FFT).
   - Oblicza wartości szczytowe (`max dB`) i średnią moc (`mean dB`).
   - Zapisuje wyniki do dwóch plików `.csv`.

4. **`sdr_samples.py`** – Odbiera próbki z urządzenia SDR i zwraca je jako `ndarray[complex64]`.

5. **`plot_csv.py`** – Tworzy wykresy z danych `.csv`, pokazuje:
   - Maksymalny poziom sygnału (`max dB`)
   - Średni poziom (`mean dB`)

## Uwagi

- `SoapySDR` nie jest w `requirements.txt`, ponieważ instaluje się go systemowo.