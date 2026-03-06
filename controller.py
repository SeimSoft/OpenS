#
# Python Model (16 Pins available)
#


class Controller:
    def __init__(self):
        """Setup input/outputs"""
        self.VDD = Input(0)  # 3.3 volt
        self.VSS = Input(15)

        self.VOUT = ResistorOutput(10, 10.0, self.VDD, self.VSS)
        self.VOUT.set_pwm(0.5, 1 / 100e3)

    def update(self, time):
        # Update each time point
        pass
