#
# Python Model (16 Pins available)
#


class Controller:
    def __init__(self):
        """Setup input/outputs"""
        self.VDD = Input(0)  # 3.3 volt
        self.VSS = Input(8)
        self.Vmeas = Input(7)
        self.Vclk = Input(5)

        self.V1 = ResistorOutput(12, 1000.0, self.VDD, self.VSS)
        self.V2 = ResistorOutput(11, 1000.0, self.VDD, self.VSS)

        fsw = 100e3
        T = 1 / fsw
        # self.V1.pattern(f"[0, dt={T/2}, 1, dt={T/2}]*100")
        # self.V2.pattern(f"[1, dt={T/2}, 0, dt={T/2}]*100")

        self.VS1 = ResistorOutput(10, 1000.0, self.VDD, self.VSS)
        self.VS2 = ResistorOutput(9, 1000.0, self.VDD, self.VSS)

        self.VS1.pattern(f"[0, dt={T/2}, 1, dt={T/2}]*100")
        self.VS2.pattern(f"[1, dt={T/2}, 0, dt={T/2}]*100")

        self.t_last = 0
        self.vsw_state = 0

    def update(self, time):
        # Update each time point

        if self.vsw_state == 1:
            self.V1.set_state(self.Vclk.get_v() > 1.65)
            self.V2.set_state(self.Vclk.get_v() < 1.65)

        if time < self.t_last:
            return
        self.t_last = time + 1 / 110e3
        if self.Vmeas.get_v() < 1.1:
            self.vsw_state = 1
        else:
            self.vsw_state = 0
