import os
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtGui import QAction
from opens_suite.plugins.base import OpenSPlugin
from opens_suite.schematic_view import SchematicView
from opens_suite.calculator_widget import CalculatorDialog
from opens_suite.waveform_viewer import WaveformViewer
import numpy as np
import traceback


class CalculatorPlugin(OpenSPlugin):
    def setup(self):
        self.calc_action = QAction(
            self.main_window.calc_icon, "Calculator", self.main_window
        )
        self.calc_action.setShortcut("?")
        self.calc_action.setStatusTip("Open Simulation Calculator")
        self.calc_action.triggered.connect(self.open_calculator)
        self.calc_action.setEnabled(False)

        self.main_window.calc_action = self.calc_action

        tools_menu = self.get_menu("&Tools")
        tools_menu.addAction(self.calc_action)

        sim_toolbar = self.get_toolbar("Simulation Toolbar")
        sim_toolbar.addAction(self.calc_action)

        # Connect to existing output dock signals
        if hasattr(self.main_window, "outputs_dock"):
            self.main_window.outputs_dock.expressionPlotTriggered.connect(
                self._plot_output_expression
            )
            self.main_window.outputs_dock.bulkPlotTriggered.connect(
                self._plot_output_expressions_bulk
            )
            self.main_window.outputs_dock.expressionCalculatorTriggered.connect(
                self._send_output_to_calculator
            )

        # Hook into tab creation/changes (need to find a way to connect dynamically if added later)
        # For simplicity, we can do it by querying all existing SchematicViews and hooking into future ones
        self._connect_all_existing_views()
        self.main_window.tabs.currentChanged.connect(self._on_tab_changed)

    def _connect_all_existing_views(self):
        for i in range(self.main_window.tabs.count()):
            view = self.main_window.tabs.widget(i)
            if isinstance(view, SchematicView):
                self._connect_view(view)

    def _on_tab_changed(self, index):
        if index < 0:
            return
        view = self.main_window.tabs.widget(index)
        if isinstance(view, SchematicView):
            self._connect_view(view)
        # Also update calculator action state
        has_results = False
        filename = getattr(view, "filename", None) if view else None
        if filename:
            sim_dir = os.path.join(os.path.dirname(filename), "simulation")
            base = os.path.splitext(os.path.basename(filename))[0]
            raw_path = os.path.join(sim_dir, f"{base}.raw")
            if os.path.exists(raw_path):
                has_results = True
        self.calc_action.setEnabled(has_results)

    def _connect_view(self, view):
        # Prevent multiple connections
        try:
            view.netSignalsPlotRequested.disconnect(self._plot_net_signals)
            view.netProbed.disconnect(self._on_net_probed)
            view.simulationFinished.disconnect(self.refresh_calculators)
        except TypeError:
            pass
        view.netSignalsPlotRequested.connect(self._plot_net_signals)
        view.netProbed.connect(self._on_net_probed)
        view.simulationFinished.connect(self.refresh_calculators)

    def refresh_calculators(self):
        if hasattr(self.main_window, "active_calculators"):
            # Filter out hidden or deleted calculators
            self.main_window.active_calculators = [
                c
                for c in self.main_window.active_calculators
                if c is not None and not c.isHidden()
            ]
            for calc in self.main_window.active_calculators:
                calc.refresh()

    def open_calculator(self):
        view = self.main_window.tabs.currentWidget()
        if not isinstance(view, SchematicView):
            return

        filename = getattr(view, "filename", None)
        if not filename:
            QMessageBox.warning(
                self.main_window,
                "Warning",
                "Save the schematic and run simulation first.",
            )
            return

        sim_dir = os.path.join(os.path.dirname(filename), "simulation")
        base = os.path.splitext(os.path.basename(filename))[0]
        raw_path = os.path.join(sim_dir, f"{base}.raw")

        if not os.path.exists(raw_path):
            QMessageBox.warning(
                self.main_window,
                "Warning",
                f"Raw results not found at: {raw_path}\nPlease run simulation first.",
            )
            return

        dialog = CalculatorDialog(raw_path, self.main_window)
        if not hasattr(self.main_window, "active_calculators"):
            self.main_window.active_calculators = []
        self.main_window.active_calculators.append(dialog)
        dialog.sendToOutputsRequested.connect(
            lambda expr: self.main_window.outputs_dock.add_expression(expr)
        )
        dialog.probeRequested.connect(lambda: self._start_probing_for_calc(dialog))
        dialog.show()
        return dialog

    def _plot_output_expression(self, expression):
        view = self.main_window.tabs.currentWidget()
        filename = getattr(view, "filename", None) if view else None
        if not filename:
            return

        sim_dir = os.path.join(os.path.dirname(filename), "simulation")
        base = os.path.splitext(os.path.basename(filename))[0]
        raw_path = os.path.join(sim_dir, f"{base}.raw")

        if not os.path.exists(raw_path):
            return

        dialog = CalculatorDialog(raw_path, self.main_window)
        # Use simple evaluate from dialog
        dialog.script_edit.setPlainText(expression)
        dialog.evaluate()
        if dialog.viewer:
            dialog.viewer.setWindowTitle(f"Plot - {expression}")

    def _plot_net_signals(self, net_name):
        view = self.main_window.tabs.currentWidget()
        filename = getattr(view, "filename", None) if view else None
        if not filename:
            return

        sim_dir = os.path.join(os.path.dirname(filename), "simulation")
        base = os.path.splitext(os.path.basename(filename))[0]
        raw_path = os.path.join(sim_dir, f"{base}.raw")

        if not os.path.exists(raw_path):
            self.main_window.status_bar.showMessage(
                "No simulation results available. Run simulation first."
            )
            return

        expressions = []
        try:
            temp_dialog = CalculatorDialog(raw_path, self.main_window)
            scope = temp_dialog._create_scope()
            all_plots = scope.get("plots", {})

            if any("Transient" in name for name in all_plots):
                expressions.append(f"vt('{net_name}')")
            if any("AC Analysis" in name for name in all_plots):
                expressions.append(f"vf('{net_name}')")
                expressions.append(f"bode('{net_name}')")
            if not expressions:
                expressions.append(f"vt('{net_name}')  # No results found yet")
        except Exception:
            expressions.append(f"vt('{net_name}')")

        dialog = CalculatorDialog(raw_path, self.main_window)
        if not hasattr(self.main_window, "active_calculators"):
            self.main_window.active_calculators = []
        self.main_window.active_calculators.append(dialog)
        dialog.script_edit.setPlainText("\n".join(expressions))
        dialog.sendToOutputsRequested.connect(
            lambda expr: self.main_window.outputs_dock.add_expression(expr)
        )
        dialog.show()

    def _send_output_to_calculator(self, expression):
        view = self.main_window.tabs.currentWidget()
        filename = getattr(view, "filename", None) if view else None
        if not filename:
            return

        sim_dir = os.path.join(os.path.dirname(filename), "simulation")
        base = os.path.splitext(os.path.basename(filename))[0]
        raw_path = os.path.join(sim_dir, f"{base}.raw")

        if not os.path.exists(raw_path):
            return

        dialog = CalculatorDialog(raw_path, self.main_window)
        if not hasattr(self.main_window, "active_calculators"):
            self.main_window.active_calculators = []
        self.main_window.active_calculators.append(dialog)
        dialog.script_edit.setPlainText(expression)
        dialog.sendToOutputsRequested.connect(
            lambda expr: self.main_window.outputs_dock.add_expression(expr)
        )
        dialog.show()

    def _plot_output_expressions_bulk(self, expressions):
        view = self.main_window.tabs.currentWidget()
        filename = getattr(view, "filename", None) if view else None
        if not filename:
            return

        sim_dir = os.path.join(os.path.dirname(filename), "simulation")
        base = os.path.splitext(os.path.basename(filename))[0]
        raw_path = os.path.join(sim_dir, f"{base}.raw")

        if not os.path.exists(raw_path):
            return

        dialog = CalculatorDialog(raw_path, self.main_window)
        # Construct multiline script
        script = "\n".join([f"plot({expr}, label='{expr}')" for expr in expressions])
        dialog.script_edit.setPlainText(script)
        dialog.evaluate()

    def _start_probing_for_calc(self, calc):
        view = self.main_window.tabs.currentWidget()
        if isinstance(view, SchematicView):
            self._probi_calc = calc
            view.set_mode(view.MODE_PROBE)
            self.main_window.status_bar.showMessage(
                "Probe Mode: Click a net to insert into calculator"
            )

    def _on_net_probed(self, net_name):
        an_type = (
            self.main_window.analysis_dock.get_current_analysis_type()
            if hasattr(self.main_window, "analysis_dock")
            else "Tran"
        )
        prefix_map = {"Tran": "vt", "AC": "vf", "OP": "op", "DC": "vdc"}
        prefix = prefix_map.get(an_type, "vt")

        expr = f"plot({prefix}('{net_name}'), label=\"{prefix}('{net_name}')\")"

        calc = getattr(self, "_probi_calc", None)
        if not calc or calc.isHidden():
            has_calcs = (
                hasattr(self.main_window, "active_calculators")
                and self.main_window.active_calculators
            )
            if has_calcs:
                self.main_window.active_calculators = [
                    c for c in self.main_window.active_calculators if not c.isHidden()
                ]

            if has_calcs and self.main_window.active_calculators:
                calc = self.main_window.active_calculators[-1]
            else:
                calc = self.open_calculator()

        if calc:
            calc.insert_expression(expr)
            calc.show()
            calc.raise_()
            calc.activateWindow()

        self._probi_calc = None
        self.main_window.status_bar.showMessage("Probing complete.", 3000)
