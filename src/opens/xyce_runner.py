import os
import platform
import subprocess
from PyQt6.QtCore import QProcess, QObject, pyqtSignal


class XyceRunner(QObject):
    simulationFinished = pyqtSignal(int, int)  # exit_code, exit_status
    readyReadStandardOutput = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None

    @classmethod
    def get_executable_path(cls):
        system = platform.system().lower()
        if system == "windows":
            plat = "win64"
            exe = "Xyce.exe"
        elif system == "darwin":
            # Check for intel_mac vs macos if necessary, default to intel_mac based on user info
            base_xyce = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xyce")
            # Prioritize intel_mac if it exists
            if os.path.exists(os.path.join(base_xyce, "intel_mac", "bin", "Xyce")):
                plat = "intel_mac"
            elif os.path.exists(os.path.join(base_xyce, "darwin", "bin", "Xyce")):
                plat = "darwin"
            else:
                plat = "macos"
            exe = "Xyce"
        else:
            plat = "linux"
            exe = "Xyce"

        xyce_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "xyce",
            plat,
            "bin",
            exe,
        )
        return xyce_path

    def run_cli(self, netlist_path, raw_path):
        """Run Xyce synchronously in CLI mode."""
        xyce_path = self.get_executable_path()
        if not os.path.exists(xyce_path):
            raise FileNotFoundError(f"Xyce executable not found at {xyce_path}")

        proc = subprocess.Popen(
            [xyce_path, "-r", raw_path, netlist_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        for line in proc.stdout:
            print(line, end="")
        proc.wait()
        return proc.returncode

    def run_async(self, netlist_path, raw_path):
        """Run Xyce asynchronously for GUI, returning the QProcess."""
        xyce_path = self.get_executable_path()
        if not os.path.exists(xyce_path):
            raise FileNotFoundError(f"Xyce executable not found at {xyce_path}")

        if self.process is not None:
            self.process.kill()
            self.process.waitForFinished()

        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)

        # Connect signals
        self.process.readyReadStandardOutput.connect(self._on_ready_read)
        self.process.finished.connect(self._on_finished)

        self.process.start(xyce_path, ["-r", raw_path, netlist_path])
        return self.process

    def _on_ready_read(self):
        if self.process:
            data = (
                self.process.readAllStandardOutput()
                .data()
                .decode("utf-8", errors="replace")
            )
            self.readyReadStandardOutput.emit(data)

    def _on_finished(self, exit_code, exit_status):
        self.simulationFinished.emit(exit_code, exit_status)
        self.process = None

    def kill(self):
        """Kill the running asynchronous process."""
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.process.kill()
            self.process.waitForFinished(3000)
            self.process = None
