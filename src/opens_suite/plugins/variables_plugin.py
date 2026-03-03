from PyQt6.QtCore import Qt
from opens_suite.plugins.base import OpenSPlugin
from opens_suite.variables_widget import VariablesWidget


class VariablesPlugin(OpenSPlugin):
    def setup(self):
        self.dock = VariablesWidget(self.main_window)
        self.main_window.variables_dock = self.dock

        self.main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)

        view_menu = self.get_menu("&View")
        view_menu.addAction(self.dock.toggleViewAction())

        # Connect signal to update netlist if needed,
        # though usually it's generated on demand.
        # self.dock.variablesChanged.connect(self._on_variables_changed)

    def _on_variables_changed(self):
        # We could trigger a re-gen or status update here
        pass
