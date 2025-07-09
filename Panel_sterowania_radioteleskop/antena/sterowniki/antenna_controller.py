"""
Biblioteka do sterowania silnikiem anteny radioteleskopu

Autor: Aleks Czarnecki
Wersja: 0.1
"""

import serial
import time
import threading
import logging
import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any, Callable
from enum import Enum

# Konfiguracja logowania
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class AntennaError(Exception):
    """Podstawowy wyjątek dla błędów anteny"""
    pass


class CommunicationError(AntennaError):
    """Błąd komunikacji z sterownikiem"""
    pass


class PositionError(AntennaError):
    """Błąd pozycjonowania anteny"""
    pass


class SafetyError(AntennaError):
    """Błąd bezpieczeństwa - przekroczenie limitów"""
    pass


class AntennaState(Enum):
    """Stany anteny"""
    IDLE = "idle"
    MOVING = "moving"
    ERROR = "error"
    STOPPED = "stopped"
    CALIBRATING = "calibrating"


@dataclass
class Position:
    """Pozycja anteny (azymut i elewacja)"""
    azimuth: float  # stopnie (0-360)
    elevation: float  # stopnie (0-90)

    def __post_init__(self):
        """Walidacja pozycji"""
        if not (0 <= self.azimuth <= 360):
            raise ValueError(f"Azymut musi być w zakresie 0-360°, otrzymano: {self.azimuth}")
        if not (0 <= self.elevation <= 90):
            raise ValueError(f"Elewacja musi być w zakresie 0-90°, otrzymano: {self.elevation}")


@dataclass
class AntennaLimits:
    """Limity mechaniczne anteny"""
    min_azimuth: float = 0.0
    max_azimuth: float = 360.0
    min_elevation: float = 0.0
    max_elevation: float = 90.0
    max_azimuth_speed: float = 5.0  # stopnie/s
    max_elevation_speed: float = 3.0  # stopnie/s


@dataclass
class MotorConfig:
    """Konfiguracja silnika"""
    steps_per_revolution: int = 200
    microsteps: int = 16
    gear_ratio_azimuth: float = 100.0
    gear_ratio_elevation: float = 80.0

    @property
    def steps_per_degree_azimuth(self) -> float:
        """Liczba kroków na stopień dla azymutu"""
        return (self.steps_per_revolution * self.microsteps * self.gear_ratio_azimuth) / 360.0

    @property
    def steps_per_degree_elevation(self) -> float:
        """Liczba kroków na stopień dla elewacji"""
        return (self.steps_per_revolution * self.microsteps * self.gear_ratio_elevation) / 360.0


class MotorDriver(ABC):
    """Abstrakcyjna klasa sterownika silnika"""

    @abstractmethod
    def connect(self) -> None:
        """Nawiązuje połączenie z sterownikiem"""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Rozłącza się ze sterownikiem"""
        pass

    @abstractmethod
    def move_to_position(self, azimuth_steps: int, elevation_steps: int) -> None:
        """Przesuwa silniki do pozycji (w krokach)"""
        pass

    @abstractmethod
    def get_position(self) -> Tuple[int, int]:
        """Zwraca aktualną pozycję w krokach (azymut, elewacja)"""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Zatrzymuje wszystkie silniki"""
        pass

    @abstractmethod
    def is_moving(self) -> bool:
        """Sprawdza czy silniki się poruszają"""
        pass


class ModbusMotorDriver(MotorDriver):
    """Sterownik silnika komunikujący się przez Modbus RTU"""

    def __init__(self, port: str, baudrate: int = 9600, slave_id: int = 1):
        self.port = port
        self.baudrate = baudrate
        self.slave_id = slave_id
        self.serial_connection: Optional[serial.Serial] = None
        self.connected = False

    def connect(self) -> None:
        """Nawiązuje połączenie Modbus RTU"""
        try:
            self.serial_connection = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1.0
            )
            self.connected = True
            logger.info(f"Połączono z sterownikiem na porcie {self.port}")
        except serial.SerialException as e:
            raise CommunicationError(f"Nie można połączyć się z portem {self.port}: {e}")

    def disconnect(self) -> None:
        """Rozłącza połączenie"""
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()
        self.connected = False
        logger.info("Rozłączono ze sterownikiem")

    def _calculate_crc(self, data: bytes) -> int:
        """Oblicza CRC16 dla Modbus RTU"""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc

    def _send_command(self, function_code: int, data: bytes) -> bytes:
        """Wysyła komendę Modbus i odbiera odpowiedź"""
        if not self.connected or not self.serial_connection:
            raise CommunicationError("Brak połączenia z sterownikiem")

        # Budowanie ramki Modbus
        frame = struct.pack('BB', self.slave_id, function_code) + data
        crc = self._calculate_crc(frame)
        frame += struct.pack('<H', crc)

        try:
            # Wysłanie komendy
            self.serial_connection.write(frame)
            time.sleep(0.1)  # Krótka pauza

            # Odbiór odpowiedzi
            response = self.serial_connection.read(64)  # Maksymalnie 64 bajty
            if len(response) < 5:  # Minimalna długość odpowiedzi
                raise CommunicationError("Niepełna odpowiedź od sterownika")

            # Sprawdzenie CRC
            received_crc = struct.unpack('<H', response[-2:])[0]
            calculated_crc = self._calculate_crc(response[:-2])
            if received_crc != calculated_crc:
                raise CommunicationError("Błąd CRC w odpowiedzi")

            return response[:-2]  # Bez CRC

        except serial.SerialException as e:
            raise CommunicationError(f"Błąd komunikacji szeregowej: {e}")

    def move_to_position(self, azimuth_steps: int, elevation_steps: int) -> None:
        """Przesuwa silniki do pozycji"""
        # Komenda zapisu do rejestrów (funkcja 0x10)
        data = struct.pack('>HHHH', 0x1000, 2, 4, azimuth_steps, elevation_steps)
        self._send_command(0x10, data)
        logger.info(f"Komenda ruchu: azymut={azimuth_steps} kroków, elewacja={elevation_steps} kroków")

    def get_position(self) -> Tuple[int, int]:
        """Zwraca aktualną pozycję w krokach"""
        # Komenda odczytu rejestrów (funkcja 0x03)
        data = struct.pack('>HH', 0x2000, 2)  # Adres 0x2000, 2 rejestry
        response = self._send_command(0x03, data)

        # Parsowanie odpowiedzi
        if len(response) >= 7:  # slave_id + function + byte_count + 4 bajty danych
            azimuth_steps, elevation_steps = struct.unpack('>HH', response[3:7])
            return azimuth_steps, elevation_steps
        else:
            raise CommunicationError("Nieprawidłowa odpowiedź pozycji")

    def stop(self) -> None:
        """Zatrzymuje wszystkie silniki"""
        data = struct.pack('>HH', 0x3000, 1)  # Komenda stopu
        self._send_command(0x06, data)
        logger.info("Zatrzymano silniki")

    def is_moving(self) -> bool:
        """Sprawdza czy silniki się poruszają"""
        # Odczyt rejestru stanu (funkcja 0x01)
        data = struct.pack('>HH', 0x4000, 1)
        response = self._send_command(0x01, data)
        if len(response) >= 4:
            status = response[3]
            return bool(status & 0x01)  # Bit 0 = ruch w toku
        return False


class SimulatedMotorDriver(MotorDriver):
    """Symulowany sterownik silnika do testów"""

    def __init__(self, simulation_speed: float = 1000.0):
        self.simulation_speed = simulation_speed  # kroków/sekundę
        self.current_azimuth = 0
        self.current_elevation = 0
        self.target_azimuth = 0
        self.target_elevation = 0
        self.moving = False
        self.connected = False
        self._stop_event = threading.Event()
        self._move_thread: Optional[threading.Thread] = None

    def connect(self) -> None:
        self.connected = True
        logger.info("Połączono z symulatorem sterownika")

    def disconnect(self) -> None:
        self.stop()
        self.connected = False
        logger.info("Rozłączono z symulatorem")

    def move_to_position(self, azimuth_steps: int, elevation_steps: int) -> None:
        if not self.connected:
            raise CommunicationError("Brak połączenia z symulatorem")

        self.target_azimuth = azimuth_steps
        self.target_elevation = elevation_steps

        if self._move_thread and self._move_thread.is_alive():
            self._stop_event.set()
            self._move_thread.join()

        self._stop_event.clear()
        self._move_thread = threading.Thread(target=self._simulate_movement)
        self._move_thread.start()

    def _simulate_movement(self) -> None:
        """Symuluje ruch silników"""
        self.moving = True

        while not self._stop_event.is_set():
            az_diff = self.target_azimuth - self.current_azimuth
            el_diff = self.target_elevation - self.current_elevation

            if abs(az_diff) < 1 and abs(el_diff) < 1:
                break

            # Oblicz krok ruchu
            time_step = 0.1  # 100ms
            max_step = int(self.simulation_speed * time_step)

            az_step = min(max_step, abs(az_diff)) * (1 if az_diff > 0 else -1)
            el_step = min(max_step, abs(el_diff)) * (1 if el_diff > 0 else -1)

            self.current_azimuth += az_step
            self.current_elevation += el_step

            time.sleep(time_step)

        self.moving = False

    def get_position(self) -> Tuple[int, int]:
        return self.current_azimuth, self.current_elevation

    def stop(self) -> None:
        self._stop_event.set()
        if self._move_thread and self._move_thread.is_alive():
            self._move_thread.join()
        self.moving = False
        logger.info("Zatrzymano symulator")

    def is_moving(self) -> bool:
        return self.moving


class AntennaController:
    """Główny kontroler anteny radioteleskopu"""

    def __init__(self, motor_driver: MotorDriver, motor_config: MotorConfig,
                 limits: AntennaLimits, update_callback: Optional[Callable] = None):
        self.motor_driver = motor_driver
        self.motor_config = motor_config
        self.limits = limits
        self.update_callback = update_callback

        self.state = AntennaState.IDLE
        self.current_position = Position(0.0, 0.0)
        self.target_position: Optional[Position] = None

        self._monitoring_thread: Optional[threading.Thread] = None
        self._monitoring_active = False
        self._stop_monitoring = threading.Event()

    def initialize(self) -> None:
        """Inicjalizuje system anteny"""
        try:
            self.motor_driver.connect()
            self._start_monitoring()
            self.state = AntennaState.IDLE
            logger.info("System anteny zainicjalizowany")
        except Exception as e:
            self.state = AntennaState.ERROR
            raise AntennaError(f"Błąd inicjalizacji: {e}")

    def shutdown(self) -> None:
        """Bezpieczne wyłączenie systemu"""
        self.stop()
        self._stop_monitoring.set()
        if self._monitoring_thread and self._monitoring_thread.is_alive():
            self._monitoring_thread.join()
        self.motor_driver.disconnect()
        logger.info("System anteny wyłączony")

    def _start_monitoring(self) -> None:
        """Uruchamia wątek monitorowania pozycji"""
        self._monitoring_active = True
        self._stop_monitoring.clear()
        self._monitoring_thread = threading.Thread(target=self._monitor_position)
        self._monitoring_thread.daemon = True
        self._monitoring_thread.start()

    def _monitor_position(self) -> None:
        """Monitoruje pozycję anteny w osobnym wątku"""
        while not self._stop_monitoring.is_set():
            try:
                az_steps, el_steps = self.motor_driver.get_position()
                azimuth = az_steps / self.motor_config.steps_per_degree_azimuth
                elevation = el_steps / self.motor_config.steps_per_degree_elevation

                self.current_position = Position(azimuth, elevation)

                # Sprawdź czy ruch się zakończył
                if self.state == AntennaState.MOVING and not self.motor_driver.is_moving():
                    self.state = AntennaState.IDLE
                    logger.info(f"Ruch zakończony. Pozycja: {self.current_position}")

                # Wywołaj callback jeśli zdefiniowany
                if self.update_callback:
                    self.update_callback(self.current_position, self.state)

            except Exception as e:
                logger.error(f"Błąd monitorowania: {e}")
                self.state = AntennaState.ERROR

            time.sleep(0.5)  # Aktualizacja co 500ms

    def _validate_position(self, position: Position) -> None:
        """Waliduje pozycję względem limitów mechanicznych"""
        if not (self.limits.min_azimuth <= position.azimuth <= self.limits.max_azimuth):
            raise SafetyError(f"Azymut {position.azimuth}° poza limitami "
                              f"({self.limits.min_azimuth}°-{self.limits.max_azimuth}°)")

        if not (self.limits.min_elevation <= position.elevation <= self.limits.max_elevation):
            raise SafetyError(f"Elewacja {position.elevation}° poza limitami "
                              f"({self.limits.min_elevation}°-{self.limits.max_elevation}°)")

    def move_to(self, position: Position) -> None:
        """Przesuwa antenę do zadanej pozycji"""
        if self.state == AntennaState.ERROR:
            raise AntennaError("System w stanie błędu - nie można wykonać ruchu")

        self._validate_position(position)

        # Przelicz stopnie na kroki
        az_steps = int(position.azimuth * self.motor_config.steps_per_degree_azimuth)
        el_steps = int(position.elevation * self.motor_config.steps_per_degree_elevation)

        try:
            self.target_position = position
            self.state = AntennaState.MOVING
            self.motor_driver.move_to_position(az_steps, el_steps)
            logger.info(f"Rozpoczęto ruch do pozycji: {position}")
        except Exception as e:
            self.state = AntennaState.ERROR
            raise PositionError(f"Błąd podczas ruchu: {e}")

    def stop(self) -> None:
        """Zatrzymuje ruch anteny"""
        try:
            self.motor_driver.stop()
            self.state = AntennaState.STOPPED
            self.target_position = None
            logger.info("Ruch anteny zatrzymany")
        except Exception as e:
            self.state = AntennaState.ERROR
            raise AntennaError(f"Błąd zatrzymania: {e}")

    def calibrate(self) -> None:
        """Kalibruje pozycję anteny (powrót do pozycji domowej)"""
        logger.info("Rozpoczęcie kalibracji...")
        self.state = AntennaState.CALIBRATING

        # Powrót do pozycji 0,0
        home_position = Position(0.0, 0.0)
        self.move_to(home_position)

        # Czekaj na zakończenie kalibracji
        while self.state == AntennaState.MOVING:
            time.sleep(0.1)

        self.state = AntennaState.IDLE
        logger.info("Kalibracja zakończona")

    def get_status(self) -> Dict[str, Any]:
        """Zwraca pełny status anteny"""
        return {
            'state': self.state.value,
            'current_position': {
                'azimuth': self.current_position.azimuth,
                'elevation': self.current_position.elevation
            },
            'target_position': {
                'azimuth': self.target_position.azimuth,
                'elevation': self.target_position.elevation
            } if self.target_position else None,
            'is_moving': self.motor_driver.is_moving() if hasattr(self.motor_driver, 'is_moving') else False,
            'limits': {
                'azimuth': (self.limits.min_azimuth, self.limits.max_azimuth),
                'elevation': (self.limits.min_elevation, self.limits.max_elevation)
            }
        }


class AntennaControllerFactory:
    """Factory do tworzenia kontrolerów anteny"""

    @staticmethod
    def create_modbus_controller(port: str, baudrate: int = 9600, slave_id: int = 1,
                                 motor_config: Optional[MotorConfig] = None,
                                 limits: Optional[AntennaLimits] = None) -> AntennaController:
        """Tworzy kontroler z sterownikiem Modbus"""
        motor_driver = ModbusMotorDriver(port, baudrate, slave_id)
        motor_config = motor_config or MotorConfig()
        limits = limits or AntennaLimits()

        return AntennaController(motor_driver, motor_config, limits)

    @staticmethod
    def create_simulator_controller(simulation_speed: float = 1000.0,
                                    motor_config: Optional[MotorConfig] = None,
                                    limits: Optional[AntennaLimits] = None) -> AntennaController:
        """Tworzy kontroler z symulatorem"""
        motor_driver = SimulatedMotorDriver(simulation_speed)
        motor_config = motor_config or MotorConfig()
        limits = limits or AntennaLimits()

        return AntennaController(motor_driver, motor_config, limits)


# Przykład użycia
if __name__ == "__main__":
    def status_callback(position: Position, state: AntennaState):
        """Callback wywoływany przy zmianie stanu"""
        print(f"Status: {state.value}, Pozycja: Az={position.azimuth:.2f}°, El={position.elevation:.2f}°")


    # Konfiguracja
    motor_config = MotorConfig(
        steps_per_revolution=200,
        microsteps=16,
        gear_ratio_azimuth=100.0,
        gear_ratio_elevation=80.0
    )

    limits = AntennaLimits(
        min_azimuth=0.0,
        max_azimuth=360.0,
        min_elevation=0.0,
        max_elevation=90.0
    )

    # Tworzenie kontrolera (symulator do testów)
    controller = AntennaControllerFactory.create_simulator_controller(
        simulation_speed=2000.0,
        motor_config=motor_config,
        limits=limits
    )

    # Przypisanie callbacku
    controller.update_callback = status_callback

    try:
        # Inicjalizacja
        controller.initialize()
        print("System zainicjalizowany")

        # Test ruchu
        target_positions = [
            Position(45.0, 30.0),
            Position(90.0, 45.0),
            Position(180.0, 60.0),
            Position(0.0, 0.0)  # powrót do pozycji domowej
        ]

        for pos in target_positions:
            print(f"\nRuch do pozycji: Az={pos.azimuth}°, El={pos.elevation}°")
            controller.move_to(pos)

            # Czekaj na zakończenie ruchu
            while controller.state == AntennaState.MOVING:
                time.sleep(0.5)

            print(f"Osiągnięto pozycję: {controller.current_position}")
            time.sleep(1)

        # Wyświetl status końcowy
        status = controller.get_status()
        print(f"\nStatus końcowy: {status}")

    except Exception as e:
        print(f"Błąd: {e}")
        logger.error(f"Błąd główny: {e}")

    finally:
        controller.shutdown()
        print("System wyłączony")
