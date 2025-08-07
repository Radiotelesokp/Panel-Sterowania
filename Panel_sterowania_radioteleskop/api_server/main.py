"""
REST API dla sterownika anteny radioteleskopu
Wykorzystuje protokół SPID do sterowania anteną i kalkulator astronomiczny

Autor: Aleks Czarnecki
Kontrybutor: Mateusz Wyrzykowski
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Optional
from contextlib import asynccontextmanager
import os
import sys
import SoapySDR
import logging
from fastapi.responses import StreamingResponse
import multiprocessing
import io

from libs.SDRLibrary.SDRLibrary import bias_tee, spectrum_scan

# Import z głównego folderu
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from libs.Sterownik.antenna_controller import (
    AntennaControllerFactory, AntennaController, Position, AntennaError,
    MotorConfig, AntennaLimits, get_best_spid_port,
    AntennaState, PositionCalibration, DEFAULT_SPID_PORT
)
from libs.Sterownik.astronomic_calculator import (
    AstronomicalCalculator, ObserverLocation, AstronomicalObjectType
)

# Konfiguracja logowania
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Globalne instancje
antenna_controller: Optional[AntennaController] = None
astro_calculator: Optional[AstronomicalCalculator] = None
current_observer_location: Optional[ObserverLocation] = None

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Lifecycle manager for FastAPI app"""
    # Startup
    logger.info("Uruchamianie API radioteleskopa...")
    yield
    # Shutdown
    global antenna_controller
    logger.info("Zamykanie API...")

    if antenna_controller:
        try:
            antenna_controller.stop()
            antenna_controller.shutdown()
        except Exception as e:
            logger.error(f"Błąd podczas zamykania: {e}")

# Inicjalizacja FastAPI
app = FastAPI(
    title="Sterownik Silnika Anteny Radioteleskopu API",
    description="REST API do sterowania anteną radioteleskopu z protokołem SPID",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Konfiguracja CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Modele Pydantic dla API
# Klasa odpowiedzialna za żądanie przeniesienia anteny w określone położenie
class PositionRequest(BaseModel):
    """Żądanie pozycji anteny"""
    azimuth: float
    elevation: float

# Klasa reprezentująca pozycję anteny
class PositionModel(BaseModel):
    """Model pozycji anteny"""
    azimuth: float
    elevation: float

class ObserverLocationModel(BaseModel):
    """Model lokalizacji obserwatora"""
    latitude: float = Field(..., ge=-90, le=90, description="Szerokość geograficzna w stopniach")
    longitude: float = Field(..., ge=-180, le=180, description="Długość geograficzna w stopniach")
    elevation: float = Field(0, ge=0, description="Wysokość n.p.m. w metrach")
    name: str = Field("Observer", description="Nazwa lokalizacji")

class ConnectionConfigModel(BaseModel):
    """Model konfiguracji połączenia"""
    port: Optional[str] = Field(None, description="Port szeregowy (auto-detect jeśli nie podano)")
    baudrate: int = Field(115200, description="Prędkość transmisji")
    use_simulator: bool = Field(False, description="Użyj symulatora zamiast prawdziwego sprzętu")

class StatusResponse(BaseModel):
    """Odpowiedź statusu anteny"""
    connected: bool
    current_position: Optional[PositionModel]
    is_moving: bool
    last_error: Optional[str]
    observer_location: Optional[ObserverLocationModel]

class AstronomicalObjectModel(BaseModel):
    """Model obiektu astronomicznego"""
    name: str = Field(..., description="Nazwa obiektu astronomicznego")
    object_type: AstronomicalObjectType = Field(..., description="Typ obiektu")

class CalibrationModel(BaseModel):
    """Model kalibracji anteny"""
    azimuth_offset: float = Field(0.0, description="Offset azymutu w stopniach")
    elevation_offset: float = Field(0.0, description="Offset elewacji w stopniach")

class AzimuthCalibrationModel(BaseModel):
    """Model kalibracji azymutu"""
    current_azimuth: Optional[float] = Field(None, description="Aktualna pozycja azymutu (jeśli None, użyje aktualnej)")
    save_to_file: bool = Field(True, description="Czy zapisać kalibrację do pliku")

class AxisMoveModel(BaseModel):
    """Model ruchu osi anteny"""
    axis: str = Field(..., description="Oś do ruchu: 'azimuth' lub 'elevation'")
    direction: str = Field(..., description="Kierunek: 'positive' lub 'negative'")
    amount: float = Field(1.0, description="Wielkość ruchu w stopniach")

# Pomocnicze funkcje
def get_antenna_controller() -> AntennaController:
    """Pobiera kontroler anteny lub rzuca wyjątek HTTP jeśli nie jest zainicjalizowany"""
    global antenna_controller
    if antenna_controller is None:
        raise HTTPException(status_code=503, detail="Kontroler anteny nie jest zainicjalizowany. Użyj /connect")
    return antenna_controller

def get_astro_calculator() -> AstronomicalCalculator:
    """Pobiera kalkulator astronomiczny lub rzuca wyjątek HTTP jeśli nie jest skonfigurowany"""
    global astro_calculator, current_observer_location
    if astro_calculator is None or current_observer_location is None:
        raise HTTPException(status_code=503, detail="Kalkulator astronomiczny nie jest skonfigurowany. Ustaw lokalizację obserwatora")
    return astro_calculator

# Endpointy API

@app.get("/", summary="Status API")
async def root():
    """Podstawowe informacje o API"""
    return {
        "name": "Sterownik Silnika Anteny Radioteleskopu API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs"
    }

@app.get("/web_interface.html")
async def get_web_interface():
    """Serwuj interfejs webowy"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    html_file = os.path.join(current_dir, "web_interface.html")
    if os.path.exists(html_file):
        return FileResponse(html_file)
    else:
        raise HTTPException(status_code=404, detail="Interfejs webowy nie został znaleziony")

@app.get("/status", response_model=StatusResponse, summary="Status systemu")
async def get_status():
    """Pobierz aktualny status systemu anteny"""
    global antenna_controller, current_observer_location

    connected = (antenna_controller is not None and
                 hasattr(antenna_controller.motor_driver, 'connected') and
                 antenna_controller.motor_driver.connected)
    current_position = None
    is_moving = False
    last_error = None

    if connected:
        try:
            # Użyj get_current_position() z kalibracją zamiast raw current_position
            pos = antenna_controller.get_current_position(apply_reverse_calibration=True)
            if pos:
                current_position = PositionModel(azimuth=pos.azimuth, elevation=pos.elevation)
            is_moving = antenna_controller.state == AntennaState.MOVING
        except Exception as e:
            last_error = str(e)
            logger.error(f"Błąd pobierania statusu: {e}")

    observer_loc = None
    if current_observer_location:
        observer_loc = ObserverLocationModel(
            latitude=current_observer_location.latitude,
            longitude=current_observer_location.longitude,
            elevation=current_observer_location.elevation,
            name=current_observer_location.name
        )

    return StatusResponse(
        connected=connected,
        current_position=current_position,
        is_moving=is_moving,
        last_error=last_error,
        observer_location=observer_loc
    )

@app.post("/connect", summary="Połącz z anteną")
async def connect_antenna(config: ConnectionConfigModel):
    """Nawiąż połączenie z anteną"""
    global antenna_controller

    try:
        if config.use_simulator:
            logger.info("Łączę z symulatorem...")
            antenna_controller = AntennaControllerFactory.create_simulator_controller(
                simulation_speed=2000.0,
                motor_config=MotorConfig(),
                limits=AntennaLimits()
            )
        else:
            port = config.port
            if not port:
                # Użyj domyślnego portu lub najlepszego dostępnego
                logger.info("Szukam najlepszego portu SPID...")
                port = get_best_spid_port()
                logger.info(f"Wybrany port: {port}")

            logger.info(f"Łączę z portem {port}...")
            antenna_controller = AntennaControllerFactory.create_spid_controller(
                port=port,
                baudrate=config.baudrate,
                motor_config=MotorConfig(),
                limits=AntennaLimits()
            )

        # Inicjalizuj kontroler
        antenna_controller.initialize()

        logger.info("Połączenie nawiązane pomyślnie")
        return {"status": "connected", "port": config.port, "simulator": config.use_simulator}

    except Exception as e:
        logger.error(f"Błąd połączenia: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd połączenia: {str(e)}")

@app.post("/disconnect", summary="Rozłącz z anteną")
async def disconnect_antenna():
    """Rozłącz z anteną"""
    global antenna_controller

    try:
        if antenna_controller:
            antenna_controller.stop()
            antenna_controller.shutdown()
            antenna_controller = None

        logger.info("Rozłączono z anteną")
        return {"status": "disconnected"}

    except Exception as e:
        logger.error(f"Błąd rozłączania: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd rozłączania: {str(e)}")

@app.get("/position", response_model=PositionModel, summary="Aktualna pozycja")
async def get_position():
    """Pobierz aktualną pozycję anteny (skalibrowaną)"""
    controller = get_antenna_controller()

    try:
        # Użyj get_current_position() z kalibracją zamiast raw current_position
        pos = controller.get_current_position(apply_reverse_calibration=True)
        if pos is None:
            raise HTTPException(status_code=404, detail="Nie można pobrać pozycji")

        return PositionModel(azimuth=pos.azimuth, elevation=pos.elevation)

    except Exception as e:
        logger.error(f"Błąd pobierania pozycji: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd pobierania pozycji: {str(e)}")

@app.post("/position", summary="Ustaw pozycję")
async def set_position(position: PositionModel):
    """Ustaw nową pozycję anteny"""
    controller = get_antenna_controller()

    try:
        target_pos = Position(position.azimuth, position.elevation)
        controller.move_to(target_pos)

        return {"status": "moving", "target": position.model_dump()}

    except Exception as e:
        logger.error(f"Błąd ustawiania pozycji: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd ustawiania pozycji: {str(e)}")

@app.post("/stop", summary="Zatrzymaj antenę")
async def stop_antenna():
    """Natychmiastowe zatrzymanie anteny"""
    controller = get_antenna_controller()

    try:
        controller.stop()
        logger.info("Antena zatrzymana")
        return {"status": "stopped"}

    except Exception as e:
        logger.error(f"Błąd zatrzymywania: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd zatrzymywania: {str(e)}")

@app.post("/observer", summary="Ustaw lokalizację obserwatora")
async def set_observer_location(location: ObserverLocationModel):
    """Ustaw lokalizację obserwatora dla obliczeń astronomicznych"""
    global astro_calculator, current_observer_location

    try:
        current_observer_location = ObserverLocation(
            latitude=location.latitude,
            longitude=location.longitude,
            elevation=location.elevation,
            name=location.name
        )

        astro_calculator = AstronomicalCalculator(current_observer_location)

        logger.info(f"Ustawiono lokalizację obserwatora: {location.name}")
        return {"status": "set", "location": location.model_dump()}

    except Exception as e:
        logger.error(f"Błąd ustawiania lokalizacji: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd ustawiania lokalizacji: {str(e)}")

@app.get("/observer", response_model=ObserverLocationModel, summary="Pobierz lokalizację obserwatora")
async def get_observer_location():
    """Pobierz aktualną lokalizację obserwatora"""
    global current_observer_location

    if current_observer_location is None:
        raise HTTPException(status_code=404, detail="Lokalizacja obserwatora nie jest ustawiona")

    return ObserverLocationModel(
        latitude=current_observer_location.latitude,
        longitude=current_observer_location.longitude,
        elevation=current_observer_location.elevation,
        name=current_observer_location.name
    )

@app.post("/track/{object_name}", summary="Śledź obiekt astronomiczny")
async def track_object(object_name: str, object_type: AstronomicalObjectType = AstronomicalObjectType.SUN):
    """Rozpocznij śledzenie obiektu astronomicznego"""
    controller = get_antenna_controller()
    calculator = get_astro_calculator()

    try:
        # Oblicz pozycję obiektu
        if object_type == AstronomicalObjectType.SUN:
            position = calculator.get_sun_position()
        elif object_type == AstronomicalObjectType.MOON:
            position = calculator.get_moon_position()
        elif object_name.lower() in ["mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune"]:
            planet_type = AstronomicalObjectType(object_name.lower())
            position = calculator.get_planet_position(planet_type)
        else:
            position = calculator.get_star_position(object_name)

        if position is None or not position.is_visible:
            raise HTTPException(status_code=404, detail=f"Obiekt {object_name} nie jest widoczny")

        # Konwertuj na pozycję anteny i przesuń
        antenna_position = position.to_antenna_position()
        if antenna_position:
            controller.move_to(antenna_position)
        else:
            raise HTTPException(status_code=400, detail=f"Obiekt {object_name} jest poza zasięgiem anteny")

        logger.info(f"Przesunięto antenę do obiektu: {object_name}")
        return {
            "status": "moved_to_object",
            "object": object_name,
            "type": object_type.value,
            "position": {"azimuth": position.azimuth, "elevation": position.elevation}
        }

    except Exception as e:
        logger.error(f"Błąd pozycjonowania na obiekt: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd pozycjonowania na obiekt: {str(e)}")

@app.post("/stop_tracking", summary="Zatrzymaj śledzenie")
async def stop_tracking():
    """Zatrzymaj śledzenie obiektu"""
    controller = get_antenna_controller()

    try:
        controller.stop()
        logger.info("Zatrzymano śledzenie")
        return {"status": "tracking_stopped"}

    except Exception as e:
        logger.error(f"Błąd zatrzymywania śledzenia: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd zatrzymywania śledzenia: {str(e)}")

@app.get("/ports", summary="Lista dostępnych portów")
async def list_ports():
    """Lista dostępnych portów szeregowych"""
    try:
        # Zwróć domyślny port SPID
        return {"ports": [DEFAULT_SPID_PORT], "default_port": DEFAULT_SPID_PORT}

    except Exception as e:
        logger.error(f"Błąd listowania portów: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd listowania portów: {str(e)}")

@app.get("/diagnostic", summary="Diagnostyka połączenia")
async def diagnostic():
    """Sprawdź czy rotctl i SPID działają"""
    try:
        import subprocess

        # Test rotctl
        rotctl_result = subprocess.run(['rotctl', '--version'],
                                       capture_output=True, text=True, timeout=5, check=False)
        rotctl_available = rotctl_result.returncode == 0

        # Test połączenia ze SPID
        spid_result = subprocess.run(['rotctl', '-m', '903', '-r', DEFAULT_SPID_PORT,
                                      '-s', '115200', '-t', '2', 'get_pos'],
                                     capture_output=True, text=True, timeout=10, check=False)
        spid_connected = spid_result.returncode == 0

        return {
            "rotctl_available": rotctl_available,
            "rotctl_version": rotctl_result.stdout.strip() if rotctl_available else "N/A",
            "spid_connected": spid_connected,
            "spid_error": spid_result.stderr.strip() if not spid_connected else "OK",
            "default_port": DEFAULT_SPID_PORT,
            "recommendation": ("Użyj symulatora jeśli SPID nie odpowiada"
                               if not spid_connected else "SPID ready")
        }

    except Exception as e:
        logger.error(f"Błąd diagnostyki: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd diagnostyki: {str(e)}")

@app.get("/astronomical/position/{object_name}", summary="Pozycja obiektu astronomicznego")
async def get_astronomical_position(object_name: str):
    """Pobierz aktualną pozycję obiektu astronomicznego"""
    calculator = get_astro_calculator()

    try:
        object_name_lower = object_name.lower()

        # Mapowanie obiektów na właściwe typy
        if object_name_lower == "sun":
            position = calculator.get_sun_position()
        elif object_name_lower == "moon":
            position = calculator.get_moon_position()
        elif object_name_lower in ["mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune"]:
            # Konwertuj nazwę na AstronomicalObjectType
            planet_type = AstronomicalObjectType(object_name_lower)
            position = calculator.get_planet_position(planet_type)
        else:
            # Dla gwiazd i innych obiektów
            position = calculator.get_star_position(object_name)

        if position is None:
            raise HTTPException(status_code=404, detail=f"Nie można obliczyć pozycji dla obiektu: {object_name}")

        if not position.is_visible:
            logger.warning(f"Obiekt {object_name} jest pod horyzontem")

        return {
            "azimuth": position.azimuth,
            "elevation": position.elevation,
            "distance": position.distance,
            "ra": position.ra,
            "dec": position.dec,
            "is_visible": position.is_visible,
            "magnitude": position.magnitude if hasattr(position, 'magnitude') else None
        }

    except ValueError:
        logger.error(f"Nieprawidłowy obiekt astronomiczny: {object_name}")
        raise HTTPException(status_code=400, detail=f"Nieprawidłowy obiekt astronomiczny: {object_name}")
    except Exception as e:
        logger.error(f"Błąd obliczania pozycji obiektu {object_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd obliczania pozycji: {str(e)}")

@app.post("/calibrate_azimuth", summary="Kalibracja referencji azymutu")
async def calibrate_azimuth_reference(calibration: AzimuthCalibrationModel):
    """Kalibruje punkt referencyjny azymutu (ustala nowe 0°)"""
    controller = get_antenna_controller()

    try:
        controller.calibrate_azimuth_reference(
            current_azimuth=calibration.current_azimuth,
            save_to_file=calibration.save_to_file
        )

        logger.info(f"Kalibracja azymutu wykonana. Offset: {controller.position_calibration.azimuth_offset:.2f}°")
        return {
            "status": "calibrated",
            "azimuth_offset": controller.position_calibration.azimuth_offset,
            "saved_to_file": calibration.save_to_file
        }

    except Exception as e:
        logger.error(f"Błąd kalibracji azymutu: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd kalibracji azymutu: {str(e)}")

@app.get("/calibration", summary="Pobierz aktualną kalibrację")
async def get_calibration():
    """Pobierz aktualne parametry kalibracji"""
    controller = get_antenna_controller()

    try:
        cal = controller.position_calibration
        return CalibrationModel(
            azimuth_offset=cal.azimuth_offset,
            elevation_offset=cal.elevation_offset
        )

    except Exception as e:
        logger.error(f"Błąd pobierania kalibracji: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd pobierania kalibracji: {str(e)}")

@app.post("/calibration", summary="Ustaw kalibrację")
async def set_calibration(calibration: CalibrationModel):
    """Ustaw parametry kalibracji"""
    controller = get_antenna_controller()

    try:
        new_cal = PositionCalibration(
            azimuth_offset=calibration.azimuth_offset,
            elevation_offset=calibration.elevation_offset
        )

        controller.set_position_calibration(new_cal, save_to_file=True)

        logger.info("Kalibracja została ustawiona i zapisana")
        return {"status": "set", "calibration": calibration.model_dump()}

    except Exception as e:
        logger.error(f"Błąd ustawiania kalibracji: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd ustawiania kalibracji: {str(e)}")

@app.post("/reset_calibration", summary="Resetuj kalibrację")
async def reset_calibration():
    """Resetuj kalibrację do wartości domyślnych"""
    controller = get_antenna_controller()

    try:
        controller.reset_calibration(save_to_file=True)
        logger.info("Kalibracja została zresetowana do wartości domyślnych")
        return {"status": "reset", "message": "Kalibracja zresetowana do wartości domyślnych"}

    except Exception as e:
        logger.error(f"Błąd resetowania kalibracji: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd resetowania kalibracji: {str(e)}")

@app.post("/move_axis", summary="Ruch w osi")
async def move_axis(move: AxisMoveModel):
    """Porusz anteną w określonej osi o zadaną wartość"""
    controller = get_antenna_controller()

    try:
        # Użyj skalibrowanej pozycji do obliczeń
        current_pos = controller.get_current_position(apply_reverse_calibration=True)

        if move.axis.lower() == "azimuth":
            if move.direction.lower() == "positive":
                new_azimuth = (current_pos.azimuth + move.amount) % 360
            else:  # negative
                new_azimuth = (current_pos.azimuth - move.amount) % 360
            new_position = Position(azimuth=new_azimuth, elevation=current_pos.elevation)

        elif move.axis.lower() == "elevation":
            if move.direction.lower() == "positive":
                new_elevation = min(current_pos.elevation + move.amount, 90)
            else:  # negative
                new_elevation = max(current_pos.elevation - move.amount, 0)
            new_position = Position(azimuth=current_pos.azimuth, elevation=new_elevation)

        else:
            raise HTTPException(status_code=400, detail="Oś musi być 'azimuth' lub 'elevation'")

        controller.move_to(new_position)

        logger.info(f"Ruch w osi {move.axis}: {move.direction} o {move.amount}°")
        return {
            "status": "moving",
            "axis": move.axis,
            "direction": move.direction,
            "amount": move.amount,
            "new_position": {"azimuth": new_position.azimuth, "elevation": new_position.elevation}
        }

    except Exception as e:
        logger.error(f"Błąd ruchu w osi: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd ruchu w osi: {str(e)}")

#SDR
@app.get("/spectrum/biastee/status")
async def bias_tee_status():
    """Zwraca aktualny status włącznika Bias-Tee (on/off)"""
    try:
        sdr = SoapySDR.Device({})
        bias = bias_tee.BiasTee(sdr)
        return {"status": bias.getStatus()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania statusu Bias-Tee: {e}")

@app.put("/spectrum/biastee/{action}")
async def bias_tee_control(action: str):
    """Włącza lub wyłącza Bias-Tee na podstawie parametru action"""
    try:
        sdr = SoapySDR.Device({})
        bias = bias_tee.BiasTee(sdr)
        bias.controlBiasTee(action)
        return {"status": bias.getStatus()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd ustawiania Bias-Tee: {e}")

class ScanRequest(BaseModel):
    start_freq: float
    stop_freq: float
    step_freq: float
    sample_rate: float
    gain: float
    n_samples: int
    channel: int = 0

def scan_worker(start_freq, stop_freq, step_freq, sample_rate, gain, n_samples, channel, bias_tee_state, result_queue):
    """Wykonuje skanowanie widma SDR w osobnym procesie, zapisując wyniki do bufora ZIP"""
    import SoapySDR

    try:
        sdr = SoapySDR.Device({})
        bias = bias_tee.BiasTee(sdr)
        bias.controlBiasTee(bias_tee_state)

        scanner = spectrum_scan.SpectrumScanner(
            sdr=sdr,
            start_freq=start_freq,
            stop_freq=stop_freq,
            step_freq=step_freq,
            sample_rate=sample_rate,
            gain=gain,
            n_samples=n_samples,
            channel=channel
        )
        _, zip_buffer = scanner.scan()

        result_queue.put(zip_buffer.getvalue())

    except Exception as e:
        result_queue.put(f"ERROR: {e}")


@app.post("/spectrum/scan/json")
async def spectrum_scan_json(request: ScanRequest):
    """Uruchamia proces skanowania widma i zwraca wynik jako plik ZIP"""
    result_queue = multiprocessing.Queue()
    process = multiprocessing.Process(target=scan_worker, args=(
        request.start_freq,
        request.stop_freq,
        request.step_freq,
        request.sample_rate,
        request.gain,
        request.n_samples,
        request.channel,
        "on",
        result_queue
    ))
    process.start()
    process.join(timeout=10)

    if process.is_alive():
        process.terminate()
        process.join()
        raise HTTPException(status_code=500, detail="Skanowanie SDR zawiesiło się (timeout)")

    result = result_queue.get()
    if isinstance(result, str) and result.startswith("ERROR"):
        raise HTTPException(status_code=500, detail=result)

    return StreamingResponse(io.BytesIO(result), media_type="application/zip",
                             headers={"Content-Disposition": "attachment; filename=spectrum_results.zip"})

# Obsługa błędów
@app.exception_handler(AntennaError)
async def antenna_error_handler(_request, exc: AntennaError):
    """Handle antenna errors"""
    logger.error(f"Błąd anteny: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"Błąd anteny: {str(exc)}"}
    )

@app.exception_handler(Exception)
async def general_exception_handler(_request, exc: Exception):
    """Handle general exceptions"""
    import traceback
    tb_str = traceback.format_exc()
    logger.error(f"Nieoczekiwany błąd: {exc}\n{tb_str}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"Błąd serwera: {str(exc)}"}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
