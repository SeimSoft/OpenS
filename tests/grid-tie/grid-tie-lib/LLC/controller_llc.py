#
# Python Model (16 Pins available)
#


class Controller:
    def __init__(self):
        """Setup input/outputs"""
        self.VDD = Input(0)  # 3.3 volt
        self.VSS = Input(8)

        self.V1 = ResistorOutput(12, 1000.0, self.VDD, self.VSS)
        self.V2 = ResistorOutput(11, 1000.0, self.VDD, self.VSS)

        fsw = 100e3
        T = 1 / fsw
        self.V1.pattern(f"[0, dt={T/2}, 1, dt={T/2}]*100")
        self.V2.pattern(f"[1, dt={T/2}, 0, dt={T/2}]*100")

    def update(self, time):
        # Update each time point
        pass
