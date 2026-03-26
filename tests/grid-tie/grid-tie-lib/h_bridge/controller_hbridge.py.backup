#
# Python Model (16 Pins available)
#


class Controller:
    def __init__(self):
        """Setup input/outputs"""
        self.VDD = Input(0)  # 3.3 volt
        self.VSS = Input(7)

        self.en1 = Input(3)
        self.en2 = Input(4)

        self.BOOT1 = Input(10)
        self.BOOT2 = Input(13)

        self.VSW1 = Input(12)
        self.VSW2 = Input(11)

        self.VH1 = ResistorOutput(15, 10.0, self.BOOT1, self.VSW1)
        self.VH2 = ResistorOutput(14, 10.0, self.BOOT2, self.VSW2)

        self.VL1 = ResistorOutput(8, 10.0, self.VDD, self.VSS)
        self.VL2 = ResistorOutput(9, 10.0, self.VDD, self.VSS)

    def update(self, time):
        # Update each time point

        self.VL1.set_state(self.en1.get_v() < 0.5)
        self.VL2.set_state(self.en2.get_v() < 0.5)
        self.VH1.set_state(self.en1.get_v() > 0.5)
        self.VH2.set_state(self.en2.get_v() > 0.5)
