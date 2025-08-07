class BiasTee:
    def __init__(self, sdr):
        self.sdr = sdr
        self.controlBiasTee("off")

    def getStatus(self):
        state = self.sdr.readSetting("bias_tx")
        return "on" if state == "true" else "off"

    def controlBiasTee(self, action):
        if action.lower() == "on":
            self.sdr.writeSetting("bias_tx", "true")
        elif action.lower() == "off":
            self.sdr.writeSetting("bias_tx", "false")
        else:
            raise ValueError(f"Unsupported operation Bias-Tee: '{action}'")