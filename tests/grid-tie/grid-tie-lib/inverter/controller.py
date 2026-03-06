#
# Python Model (16 Pins available)
#


class Controller:
    def __init__(self):
        """Setup input/outputs"""
        self.VDD = Input(0)  # 3.3 volt
        self.VSS = Input(7)
        self.VL = ResistorOutput(13, 10.0, self.VDD, self.VSS)
        self.VR = ResistorOutput(12, 10.0, self.VDD, self.VSS)
        # Initialize to low state

        self.VL.pattern(f"0, dt=5u, 1, dt=1u, 0, dt=3.4e-6, 0, dt=3.4u, 0")

        self.VR.pattern(f"0, dt=5u, 0, dt=1u, 0, dt=3.4e-6, 1, dt=3.4u, 0")

        # self.VL.set_state(0)
        # self.VR.set_state(0)

    def update(self, time):
        # Update each time point
        pass
