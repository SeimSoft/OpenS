#
# Python Model (16 Pins available)
#


class Controller(Device):
    def __init__(self):
        """Setup input/outputs"""
        super().__init__()

        self.VDD = Input(0)  # 3.3 volt
        self.VSS = Input(8)

        self.en_1 = ResistorOutput(15, 1000.0, self.VDD, self.VSS)
        self.en_2 = ResistorOutput(12, 1000.0, self.VDD, self.VSS)

        self.i_out = Input(4)

    def update(self, time):
        if self.i_out.get_v() > 0.8:
            self.en_1.set_state(0)
            self.en_2.set_state(1)
        elif self.i_out.get_v() < 0.6:
            self.en_1.set_state(1)
            self.en_2.set_state(0)
