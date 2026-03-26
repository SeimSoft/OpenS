#
# Python Model (16 Pins available)
#


class Controller(Device):
    def __init__(self):
        """Setup input/outputs"""
        super().__init__()
        self.VDD = Input(0)  # 3.3 volt
        self.PIN1 = Input(1)
        self.VSS = Input(8)

        self.VOUT = ResistorOutput(15, 10.0, self.VDD, self.VSS)

        self.add_breakpoint(9e-9)
        self.add_breakpoint(40e-6)

        self.PIN1.trigger(self.low, +1, 0.5)
        self.PIN1.trigger(self.high, -1, 0.5)

    def high(self):
        self.VOUT.set_state(1)

    def low(self):
        self.VOUT.set_state(0)

    def update(self, time):
        if time == 9e-9:
            self.high()
        elif time == 40e-6:
            self.low()
