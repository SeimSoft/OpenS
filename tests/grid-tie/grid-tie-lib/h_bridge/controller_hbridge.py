#
# Python Model (16 Pins available)
#


class Controller(Device):
    def __init__(self):
        """Setup input/outputs"""
        super().__init__()
        self.VDD = Input(0)  # 3.3 volt
        self.VSS = Input(7)

        self.en1 = Input(3)
        self.en2 = Input(4)

        self.BOOT1 = Input(10)
        self.BOOT2 = Input(13)

        self.VSW1 = Input(12)
        self.VSW2 = Input(11)

        self.VH1 = ResistorOutput(15, 1000.0, self.BOOT1, self.VSW1)
        self.VH2 = ResistorOutput(14, 1000.0, self.BOOT2, self.VSW2)

        self.VL1 = ResistorOutput(8, 1000.0, self.VDD, self.VSS)
        self.VL2 = ResistorOutput(9, 1000.0, self.VDD, self.VSS)

        self.en1.trigger(self.P1_high, +1, 0.5)
        self.en1.trigger(self.P1_low, -1, 0.5)
        self.en2.trigger(self.P2_high, +1, 0.5)
        self.en2.trigger(self.P2_low, -1, 0.5)

        if self.en1.get_v() > 0.5:
            self.P1_high()
        else:
            self.P1_low()

        if self.en2.get_v() > 0.5:
            self.P2_high()
        else:
            self.P2_low()

    def P1_high(self):
        self.delay(lambda: self.VH1.set_state(1), 10e-9)
        self.VL1.set_state(0)

    def P1_low(self):
        self.VH1.set_state(0)
        self.delay(lambda: self.VL1.set_state(1), 10e-9)

    def P2_high(self):
        self.VL2.set_state(0)
        self.delay(lambda: self.VH2.set_state(1), 10e-9)

    def P2_low(self):
        self.VH2.set_state(0)
        self.delay(lambda: self.VL2.set_state(1), 10e-9)

    def update(self, time):
        pass
