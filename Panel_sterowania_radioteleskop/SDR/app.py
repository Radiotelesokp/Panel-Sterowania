import sys
import SoapySDR
import logging
import base64
from flask import Flask, jsonify, send_file
from SDRLibrary import BiasTee, SpectrumScanner

SoapySDR.setLogLevel(SoapySDR.SOAPY_SDR_FATAL)
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sdr = None
bias_tee = None

help="""\
SDR SERVICE OPTION

METHOD  ENDPOINT                                                                                DESCRIPTION
------  -------------------------------------------------------------------------------------   --------------------------------------
PUT     /biastee/<action>                                                                       on/off Bias-Tee
GET     /biastee/status                                                                         get Bias-Tee state
GET     /help                                                                                   show help
POST    /scan/<start_freq>/<stop_freq>/<step_freq>/<sample_rate>/<gain>/<n_samples>/<channel>   scan spectrum
"""
@app.route('/')
def home():
    return help

@app.route('/biastee/status', methods=['GET'])
def bias_tee_status():
    try:
        return jsonify({"message": f"Bias-Tee status: {bias_tee.getStatus()}"})
    except Exception as ex:
        return jsonify({"message": f"Bias-Tee get status error: {ex}"})

@app.route('/biastee/<action>', methods=['PUT'])
def bias_tee_control(action):
    try:
        bias_tee.controlBiasTee(action)
        return jsonify({"message": f"Bias-Tee status set on: {bias_tee.getStatus()}"})
    except ValueError as ex:
        return jsonify({"message": str(ex)})
    except Exception as ex:
        return jsonify({"message": f"Bias-Tee set status error: {ex}"})

@app.route('/scan/<start_freq>/<stop_freq>/<step_freq>/<sample_rate>/<gain>/<n_samples>/<channel>', methods=['POST'])
def scan_spectrum(start_freq, stop_freq, step_freq, sample_rate, gain, n_samples, channel):
    try:
        spectrumScanner = SpectrumScanner(sdr, start_freq, stop_freq, step_freq, sample_rate, gain, n_samples, channel)
        logger.info("Starting spectrum scan. Please wait...")
        result, zipfile = spectrumScanner.scan()
        logger.info("Success spectrum scan.")
        zip_base64 = base64.b64encode(zipfile.read()).decode('utf-8')

        return jsonify({
            "message": f"Data: {result}",
            "filename": "spectrum_file.zip",
            "zip_base64": zip_base64
        })

    except (TypeError, ValueError) as ex:
        return jsonify({"message": f"Please give correct parameters. Error: {ex}"})
    except RuntimeError as ex:
        return jsonify({"message": f"SDR have problem: {ex}"})
    except Exception as ex:
        return jsonify({"message": f"Error: {str(ex)}"})

@app.route('/help', methods=['GET'])
def get_help():
    return help

if __name__ == '__main__':
    try:
        args = dict(driver="hackrf")
        sdr = SoapySDR.Device(args)
        driver = sdr.getDriverKey().lower()
        logger.info(f"Used driver SDR: {driver}")
        if driver != "hackrf":
           raise ValueError(f"No SDR supported - required 'hackrf, but is {driver}")

        bias_tee = BiasTee(sdr)
    except Exception as ex:
        sys.exit(f"Connection error with SDR: {ex}")

    app.run(debug=True)