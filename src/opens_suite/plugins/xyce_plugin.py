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


class XycePlugin(OpenSPlugin):
    def setup(self):
        self.netlist_action = QAction(
            self.main_window.style().standardIcon(
                QStyle.StandardPixmap.SP_FileDialogDetailedView
            ),
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

        try:
            # Get variables if available
            variables = []
            if hasattr(self.main_window, "variables_dock"):
                variables = self.main_window.variables_dock.get_variables()

            generator = NetlistGenerator(view.scene(), analyses, variables=variables)
            netlist = generator.generate()

            # Show in Simulation Log
            self.main_window.simulation_text.clear()
            self.main_window.simulation_text.setPlainText(netlist)
            self.main_window.simulation_dock.setWindowTitle("Netlist")
            self.main_window.simulation_dock.show()

        except Exception as e:
            QMessageBox.critical(self.main_window, "Netlist Error", str(e))
            import traceback

            traceback.print_exc()

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
                "background-color: #fbc02d; color: black; font-weight: bold;"
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

        generator = NetlistGenerator(view.scene(), analyses, variables=variables)
        netlist = generator.generate()

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

            self.main_window.simulation_text.clear()
            self.main_window.simulation_dock.setWindowTitle(f"Simulation Log - {base}")
            self.main_window.simulation_dock.show()

            # Update action to 'Stop' mode
            self.simulate_action.setIcon(self.main_window.stop_icon)
            self.simulate_action.setText("Stop Simulation")

            self.main_window.simulation_log.sendInputRequested.connect(
                self._on_simulation_send_input
            )

            # run_async already starts the process. No need to call start() again.
            if (
                self.main_window.simulation_process.state()
                == QProcess.ProcessState.NotRunning
            ):
                if not self.main_window.simulation_process.waitForStarted():
                    self.main_window.status_bar.showMessage("Failed to start Xyce")
                    self.simulate_action.setIcon(self.main_window.play_icon)
                    self.simulate_action.setText("Simulate")
                    self.main_window.simulation_process = None

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
                "background-color: #2e7d32; color: white; font-weight: bold;"
            )
            self.main_window.status_bar.showMessage("Simulation Complete")
            if (
                self.main_window.current_simulation_view
                and self.main_window.current_raw_path
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
        else:
            self.main_window.status_bar.setStyleSheet(
                "background-color: #c62828; color: white; font-weight: bold;"
            )
            self.main_window.status_bar.showMessage(
                f"Simulation Failed (Exit Code {exit_code})"
            )

        self.main_window._update_action_states()
        self.main_window.simulation_process = None
        self.main_window.current_simulation_view = None
