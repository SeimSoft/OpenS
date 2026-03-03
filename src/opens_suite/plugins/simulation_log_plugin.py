from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDockWidget
from opens_suite.plugins.base import OpenSPlugin
from opens_suite.view.simulation_log_widget import SimulationLogWidget


class SimulationLogPlugin(OpenSPlugin):
    def setup(self):
        self.dock = QDockWidget("Simulation Log", self.main_window)
        self.log_widget = SimulationLogWidget(self.dock)
        self.dock.setWidget(self.log_widget)

        # Backwards compatibility for existing plugins using self.main_window.simulation_text
        self.main_window.simulation_dock = self.dock
        self.main_window.simulation_log = self.log_widget
        self.main_window.simulation_text = self.log_widget.text_edit

        self.main_window.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea, self.dock
        )
        self.dock.hide()
