import os
from PyQt6.QtWidgets import (
    QMessageBox,
    QDialog,
    QVBoxLayout,
    QTextEdit,
    QDialogButtonBox,
    QStyle,
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import QProcess
from opens_suite.plugins.base import OpenSPlugin
from opens_suite.schematic_view import SchematicView
from opens_suite.netlister import NetlistGenerator
from opens_suite.xyce_runner import XyceRunner
from PyQt6.QtCore import QThread, pyqtSignal
import traceback


class NetlistWorker(QThread):
    finished = pyqtSignal(str, str)  # netlist content, error
    
    def __init__(self, scene, analyses, variables):
        super().__init__()
        self.scene = scene
        self.analyses = analyses
        self.variables = variables
        
    def run(self):
        try:
            from opens_suite.netlister import NetlistGenerator
            generator = NetlistGenerator(self.scene, self.analyses, variables=self.variables)
            netlist = generator.generate()
            self.finished.emit(netlist, "")
        except Exception as e:
            traceback.print_exc()
            self.finished.emit("", str(e))


class XycePlugin(OpenSPlugin):
    def setup(self):
        import qtawesome as qta
        self.netlist_icon = qta.icon("mdi6.text-box-outline", color="#1f1f1f")
        self.netlist_action = QAction(
            self.netlist_icon,
            "Create Netlist",
            self.main_window,
        )
        self.netlist_action.setShortcut("F4")
        self.netlist_action.setStatusTip("Generate Xyce Netlist")
        self.netlist_action.triggered.connect(self.create_netlist)

        self.simulate_action = QAction(
            self.main_window.play_icon, "Simulate", self.main_window
        )
        self.simulate_action.setShortcut("F5")
        self.simulate_action.setStatusTip("Run Xyce Simulation")
        self.simulate_action.triggered.connect(self.run_simulation)

        self.main_window.netlist_action = self.netlist_action
        self.main_window.simulate_action = self.simulate_action

        tools_menu = self.get_menu("&Tools")
        tools_menu.addAction(self.netlist_action)
        tools_menu.addAction(self.simulate_action)

        sim_toolbar = self.get_toolbar("Simulation Toolbar")
        sim_toolbar.addAction(self.netlist_action)
        sim_toolbar.addAction(self.simulate_action)

    def create_netlist(self):
        view = self.main_window.tabs.currentWidget()
        if not isinstance(view, SchematicView):
            return

        # Ensure connectivity is up to date
        view.recalculate_connectivity()
        analyses = self.main_window.analysis_dock.get_all_analyses()

        # Get variables if available
        variables = []
        if hasattr(self.main_window, "variables_dock"):
            variables = self.main_window.variables_dock.get_variables()

        self.main_window.simulation_text.clear()
        self.main_window.simulation_text.append("Generating Netlist in background...")
        self.main_window.simulation_dock.setWindowTitle("Netlist")
        self.main_window.simulation_dock.show()
        
        self.netlist_action.setEnabled(False)
        self.simulate_action.setEnabled(False)

        self.worker = NetlistWorker(view.scene(), analyses, variables)
        self.worker.finished.connect(self._on_create_netlist_finished)
        self.worker.start()

    def _on_create_netlist_finished(self, netlist, error):
        self.netlist_action.setEnabled(True)
        self.simulate_action.setEnabled(True)
        if error:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self.main_window, "Netlist Error", error)
            return

        self.main_window.simulation_text.setPlainText(netlist)

    def run_simulation(self):
        # If currently simulating, then this button acts as 'Stop'
        if (
            self.main_window.simulation_process is not None
            and self.main_window.simulation_process.state()
            == QProcess.ProcessState.Running
        ):
            self.main_window.simulation_process.kill()
            self.main_window.status_bar.showMessage("Simulation Aborted")
            self.main_window.status_bar.setStyleSheet(
                "background-color: #fff3cd; color: #856404; font-weight: bold;"
            )
            return

        view = self.main_window.tabs.currentWidget()
        if not isinstance(view, SchematicView):
            return

        # 1. Ensure File is Saved (to have a base path)
        filename = getattr(view, "filename", None)
        if not filename:
            res = QMessageBox.question(
                self.main_window,
                "Save Schematic",
                "The schematic must be saved before simulating. Save now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if res == QMessageBox.StandardButton.Yes:
                self.main_window.save_file()
                filename = getattr(view, "filename", None)
                if not filename:
                    return
            else:
                return
        elif view.is_modified():
            # Automatically save if modified before simulation
            self.main_window.save_file()

        # 2. Create simulation directory
        sim_dir = os.path.join(os.path.dirname(filename), "simulation")
        os.makedirs(sim_dir, exist_ok=True)

        base = os.path.splitext(os.path.basename(filename))[0]
        netlist_path = os.path.join(sim_dir, f"{base}.net")
        log_path = os.path.join(sim_dir, f"{base}.log")
        raw_path = os.path.join(sim_dir, f"{base}.raw")

        # 3. Generate Netlist
        view.recalculate_connectivity()
        analyses = self.main_window.analysis_dock.get_all_analyses()

        # Get variables if available
        variables = []
        if hasattr(self.main_window, "variables_dock"):
            variables = self.main_window.variables_dock.get_variables()

        self.main_window.status_bar.showMessage("Generating netlist in background...")
        self.main_window.simulation_text.clear()
        self.main_window.simulation_text.append("Building connectivity graph and generating Xyce netlist...")
        self.main_window.simulation_dock.setWindowTitle(f"Simulation Log - {base}")
        self.main_window.simulation_dock.show()
        
        # Update action to 'Stop' mode
        self.simulate_action.setIcon(self.main_window.stop_icon)
        self.simulate_action.setText("Stop Simulation")

        self.worker = NetlistWorker(view.scene(), analyses, variables)
        self.worker.finished.connect(lambda netlist, err: self._on_sim_netlist_finished(netlist, err, view, netlist_path, raw_path, log_path, base))
        self.worker.start()

    def _on_sim_netlist_finished(self, netlist, error, view, netlist_path, raw_path, log_path, base):
        if self.simulate_action.text() == "Simulate":
            return # Aborted by user while netlisting

        if error:
            self.main_window.simulation_text.append(f"\nNetlisting failed:\n{error}")
            self.main_window.status_bar.showMessage("Netlisting failed.")
            self.simulate_action.setIcon(self.main_window.play_icon)
            self.simulate_action.setText("Simulate")
            return

        try:
            with open(netlist_path, "w") as f:
                f.write(netlist)

            # 4. Run Xyce in Background
            self.main_window.status_bar.setStyleSheet("")
            self.main_window.status_bar.showMessage("Running simulation...")

            if not hasattr(self.main_window, "xyce_runner"):
                self.main_window.xyce_runner = XyceRunner(self.main_window)
                self.main_window.xyce_runner.readyReadStandardOutput.connect(
                    self._on_simulation_ready_read
                )
                self.main_window.xyce_runner.simulationFinished.connect(
                    self._on_simulation_finished
                )

            # Keep a reference to the process for the kill/stop logic
            self.main_window.simulation_process = (
                self.main_window.xyce_runner.run_async(netlist_path, raw_path)
            )

            self.main_window.current_simulation_view = view
            self.main_window.current_raw_path = raw_path
            self.main_window.current_log_path = log_path

            self.main_window.simulation_log.sendInputRequested.connect(
                self._on_simulation_send_input
            )

            # run_async already starts the process. No need to call start() again.
            if (
                self.main_window.simulation_process.state()
                == QProcess.ProcessState.NotRunning
            ):
                raise Exception("Failed to start Xyce process.")

        except FileNotFoundError:
            QMessageBox.critical(
                self.main_window,
                "Error",
                "Xyce not found. Please ensure 'Xyce' is installed and in your PATH.",
            )
        except Exception as e:
            QMessageBox.critical(
                self.main_window,
                "Error",
                f"An unexpected error occurred during simulation: {e}",
            )
            import traceback

            traceback.print_exc()

    def _on_simulation_ready_read(self, data):
        self.main_window.simulation_text.insertPlainText(data)
        self.main_window.simulation_text.ensureCursorVisible()

    def _on_simulation_send_input(self, text):
        if (
            self.main_window.simulation_process
            and self.main_window.simulation_process.state()
            == QProcess.ProcessState.Running
        ):
            self.main_window.simulation_process.write(text.encode("utf-8"))

    def _on_simulation_finished(self, exit_code, exit_status):
        self.simulate_action.setIcon(self.main_window.play_icon)
        self.simulate_action.setText("Simulate")

        # Clean up input connection
        try:
            self.main_window.simulation_log.sendInputRequested.disconnect(
                self._on_simulation_send_input
            )
        except Exception:
            pass

        if exit_code == 0:
            self.main_window.status_bar.setStyleSheet(
                "background-color: #d4edda; color: #155724; font-weight: bold;"
            )
            self.main_window.status_bar.showMessage("Simulation Complete")
        else:
            self.main_window.status_bar.setStyleSheet(
                "background-color: #f8d7da; color: #721c24; font-weight: bold;"
            )
            self.main_window.status_bar.showMessage(
                f"Simulation Failed (Exit Code {exit_code})"
            )

        # Proactively load results even on failure
        if (
            self.main_window.current_simulation_view
            and self.main_window.current_raw_path
            and os.path.exists(self.main_window.current_raw_path)
        ):
            self.main_window.current_simulation_view.load_simulation_results(
                self.main_window.current_raw_path
            )
            self.main_window.current_simulation_view.simulationFinished.emit()

        # Save the log to file as well if needed
        if hasattr(self.main_window, "current_log_path"):
            try:
                with open(self.main_window.current_log_path, "w") as f:
                    f.write(self.main_window.simulation_text.toPlainText())
            except Exception:
                pass

        self.main_window._update_action_states()
        self.main_window.simulation_process = None
        self.main_window.current_simulation_view = None
