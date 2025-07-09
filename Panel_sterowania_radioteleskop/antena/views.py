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

controller = AntennaControllerFactory.create_simulator_controller(
    simulation_speed=1000.0,
    motor_config=MotorConfig(),
    limits=AntennaLimits()
)

controller.initialize()

def panel_view(request):
    return render(request, "antena/panel.html")

def cmd_position(args):
    pos = controller.get_status()["current_position"]
    return f"Pozycja: Az={pos['azimuth']:.2f}°, El={pos['elevation']:.2f}°"

def cmd_status(args):
    return json.dumps(controller.get_status(), indent=2)

def cmd_stop(args):
    controller.stop()
    return "Zatrzymano ruch"

def cmd_calibrate(args):
    controller.calibrate()
    return "Kalibracja zakończona"

def cmd_shutdown(args):
    controller.shutdown()
    return "Sterownik wyłączony"

def cmd_init(args):
    controller.initialize()
    return "Sterownik zainicjalizowany"

def cmd_move(args):
    if len(args) != 2:
        return "Użycie: move AZ EL"
    az, el = map(float, args)
    controller.move_to(Position(az, el))
    return f"Ruch do Az={az}°, El={el}°"

COMMANDS = {
    "position": cmd_position,
    "status": cmd_status,
    "stop": cmd_stop,
    "calibrate": cmd_calibrate,
    "shutdown": cmd_shutdown,
    "init": cmd_init,
    "move": cmd_move,
}

@csrf_exempt
def handle_command(request):
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