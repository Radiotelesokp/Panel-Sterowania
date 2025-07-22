from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
import json
from .sterowniki.antenna_controller import (
    AntennaControllerFactory,
    MotorConfig,
    AntennaLimits,
    Position
)
import base64
import SoapySDR
from .sdr import BiasTee, SpectrumScanner

controller = AntennaControllerFactory.create_simulator_controller(
    simulation_speed=1000.0,
    motor_config=MotorConfig(),
    limits=AntennaLimits()
)

controller.initialize()

def panel_view(request):
    return render(request, "antena/panel.html")

def cmd_driver_position(args):
    pos = controller.get_status()["current_position"]
    return f"Pozycja: Az={pos['azimuth']:.2f}°, El={pos['elevation']:.2f}°"

def cmd_driver_status(args):
    return json.dumps(controller.get_status(), indent=2)

def cmd_driver_stop(args):
    controller.stop()
    return "Zatrzymano ruch"

def cmd_driver_calibrate(args):
    controller.calibrate()
    return "Kalibracja zakończona"

def cmd_driver_shutdown(args):
    controller.shutdown()
    return "Sterownik wyłączony"

def cmd_driver_init(args):
    controller.initialize()
    return "Sterownik zainicjalizowany"

def cmd_driver_move(args):
    if len(args) != 2:
        return "Użycie: move AZ EL"
    az, el = map(float, args)
    controller.move_to(Position(az, el))
    return f"Ruch do Az={az}°, El={el}°"

def cmd_driver_help(args):
    return (
        "Dostępne komendy:\n"
        "position       - pozycja anteny\n"
        "status         - status sterownika\n"
        "stop           - zatrzymaj ruch anteny\n"
        "calibrate      - kalibracja anteny\n"
        "shutdown       - wyłączenie sterowników\n"
        "init           - włączenie sterowników\n"
        "move AZ EL     - ruch silnika na pozycje AZ EL"
    )

COMMANDS = {
    "position": cmd_driver_position,
    "status": cmd_driver_status,
    "stop": cmd_driver_stop,
    "calibrate": cmd_driver_calibrate,
    "shutdown": cmd_driver_shutdown,
    "init": cmd_driver_init,
    "move": cmd_driver_move,
    "help": cmd_driver_help
}

def cmd_sdr_bias(args, sdr):
    bias = BiasTee(sdr)
    if len(args) != 1 or args[0] not in ("on", "off"):
        return "Użycie: bias on|off"
    bias.controlBiasTee(args[0])
    return f"Bias-Tee ustawiono na: {bias.getStatus()}"

def cmd_sdr_bias_status(args, sdr):
    bias = BiasTee(sdr)
    return f"Bias-Tee: {bias.getStatus()}"

def cmd_sdr_scan(args, sdr):
    scanner = SpectrumScanner(
        sdr=sdr,
        start_freq=args[0] if len(args) > 0 else "100000000",
        stop_freq=args[1] if len(args) > 1 else "110000000",
        step_freq=args[2] if len(args) > 2 else "1000000",
        sample_rate=args[3] if len(args) > 3 else "2000000",
        gain=args[4] if len(args) > 4 else "20",
        n_samples=args[5] if len(args) > 5 else "4096",
        channel=args[6] if len(args) > 6 else "0"
    )
    result, zip_data = scanner.scan()
    zip_b64 = base64.b64encode(zip_data.read()).decode("utf-8")
    return {
        "output": "Skanowanie zakończone. Wygenerowano wykres.",
        "base64_zip": zip_b64
    }

def cmd_sdr_help(args, sdr):
    return (
        "Dostępne komendy:\n"
        "bias on|off       - włącz/wyłącz Bias-Tee\n"
        "bias_status       - sprawdź stan Bias-Tee\n"
        "scan [start stop krok SR gain próbki kanał] - skanuj\n"
    )

SDR_COMMANDS = {
    "bias": cmd_sdr_bias,
    "bias_status": cmd_sdr_bias_status,
    "scan": cmd_sdr_scan,
    "help": cmd_sdr_help,
}

@csrf_exempt
def handle_driver_command(request):
    if request.method != "POST":
        return JsonResponse({"output": "Tylko POST"})

    try:
        data = json.loads(request.body)
        cmd_line = data.get("command", "").strip()

        if not cmd_line:
            return JsonResponse({"output": "Pusta komenda"})

        parts = cmd_line.split()
        name, args = parts[0], parts[1:]

        handler = COMMANDS.get(name)
        if not handler:
            return JsonResponse({"output": f"Nieznana komenda: {name}"})

        output = handler(args)
        return JsonResponse({"output": output})

    except Exception as e:
        return JsonResponse({"output": f"Błąd: {str(e)}"})

@csrf_exempt
def handle_sdr_command(request):
    if request.method != "POST":
        return JsonResponse({"output": "Tylko POST"})

    try:
        data = json.loads(request.body)
        cmd_line = data.get("command", "").strip()
        if not cmd_line:
            return JsonResponse({"output": "Pusta komenda"})

        parts = cmd_line.split()
        name, args = parts[0], parts[1:]

        handler = SDR_COMMANDS.get(name)
        if not handler:
            return JsonResponse({"output": f"Nieznana komenda: {name}"})

        sdr = SoapySDR.Device(dict(driver="hackrf"))
        result = handler(args, sdr)

        if isinstance(result, dict):
            return JsonResponse(result)
        return JsonResponse({"output": result})

    except Exception as e:
        return JsonResponse({"output": f"Błąd: {str(e)}"})
