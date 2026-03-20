from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDockWidget
from opens_suite.plugins.base import OpenSPlugin
from opens_suite.view.simulation_log_widget import SimulationLogWidget
from opens_suite.schematic_view import SchematicView
import subprocess
import shlex
from PyQt6.QtCore import Qt, QSettings, QProcess


class SimulationLogPlugin(OpenSPlugin):
    def setup(self):
        self.dock = QDockWidget("Simulation Log", self.main_window)
        self.log_widget = SimulationLogWidget(self.dock)
        self.dock.setWidget(self.log_widget)

        # Backwards compatibility for existing plugins using self.main_window.simulation_text
        self.main_window.simulation_dock = self.dock
        self.main_window.simulation_log = self.log_widget
        self.main_window.simulation_text = self.log_widget.text_edit

        self.log_widget.copilotAnalysisRequested.connect(self.run_copilot_analysis)
        # Handle input field (stdin vs copilot)
        self.log_widget.sendInputRequested.connect(self._on_log_input)

        self.main_window.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea, self.dock
        )
        self.dock.hide()

        self.copilot_process = None

    def _on_log_input(self, text):
        # Determine if we send to simulation or ask copilot
        is_running = False
        if hasattr(self.main_window, "simulation_process") and self.main_window.simulation_process:
            from PyQt6.QtCore import QProcess
            if self.main_window.simulation_process.state() == QProcess.ProcessState.Running:
                is_running = True
        
        if is_running:
            # Traditional stdin pipe handled by main_window or xyce_plugin
            # We just need to make sure it's passed through
            if hasattr(self.main_window, "on_simulation_input"):
                self.main_window.on_simulation_input(text)
        else:
            # Ask copilot with this specific prompt
            self.run_copilot_analysis(user_prompt=text.strip())

    def run_copilot_analysis(self, user_prompt=None):
        if self.copilot_process and self.copilot_process.state() != QProcess.ProcessState.NotRunning:
            return

        view = self.main_window.tabs.currentWidget()
        if not isinstance(view, SchematicView):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self.main_window, "No Active Schematic", "Please open a schematic to analyze.")
            return

        # Disable button during analysis
        if hasattr(self.log_widget, "copilot_btn"):
            self.log_widget.copilot_btn.setEnabled(False)

        # 1. Generate Netlist
        analyses = []
        if hasattr(self.main_window, "analysis_dock"):
            analyses = self.main_window.analysis_dock.get_all_analyses()
        
        variables = []
        if hasattr(self.main_window, "variables_dock"):
            variables = self.main_window.variables_dock.get_variables()
        
        from opens_suite.netlister import NetlistGenerator
        try:
            generator = NetlistGenerator(view.scene(), analyses, variables=variables)
            netlist = generator.generate()
        except Exception as e:
            self.log_widget.appendText(f"\n[Error] Failed to generate netlist for analysis: {e}\n")
            if hasattr(self.log_widget, "copilot_btn"):
                self.log_widget.copilot_btn.setEnabled(True)
            return

        # 2. Get Log content
        log_text = self.log_widget.text_edit.toPlainText()

        # 3. Setup Prompt
        if user_prompt:
            header = f"\n\n--- AI Analysis: '{user_prompt}' ---\n"
            base_prompt = f"Regarding the user question '{user_prompt}', analyze this netlist and simulation log:\n\n"
        else:
            header = "\n\n--- AI Error Analysis (GitHub Copilot) ---\n"
            base_prompt = "Analyze this simulation netlist and log for errors:\n\n"
        
        full_prompt = f"{base_prompt}Netlist:\n{netlist}\n\nLog:\n{log_text}"
        
        self.log_widget.appendText(header)
        self.log_widget.appendText("Connecting to AI service...\n")

        # 4. Get command from settings
        settings = QSettings("OpenS", "OpenS")
        cmd_template = settings.value("ai_command", "copilot -ps '%s'")
        
        try:
            # Parse command template safely
            cmd_parts = shlex.split(cmd_template)
            # Replace %s with our prompt in the correct argument
            final_args = [p.replace("%s", full_prompt) if "%s" in p else p for p in cmd_parts]
            
            if not final_args:
                raise ValueError("AI command is empty")
                
            program = final_args[0]
            args = final_args[1:]

            # 5. Launch QProcess for streaming
            self.copilot_process = QProcess()
            self.copilot_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            self.copilot_process.readyReadStandardOutput.connect(self._on_copilot_ready_read)
            self.copilot_process.finished.connect(self._on_copilot_finished)
            
            self.copilot_process.start(program, args)
            
        except Exception as e:
            self.log_widget.appendText(f"\n[Error] Failed to start AI process: {e}\n")
            if hasattr(self.log_widget, "copilot_btn"):
                self.log_widget.copilot_btn.setEnabled(True)

    def _on_copilot_ready_read(self):
        data = self.copilot_process.readAllStandardOutput().data().decode()
        self.log_widget.appendText(data)

    def _on_copilot_finished(self):
        self.log_widget.appendText("\n--- Analysis Complete ---\n")
        if hasattr(self.log_widget, "copilot_btn"):
            self.log_widget.copilot_btn.setEnabled(True)
        self.copilot_process = None
