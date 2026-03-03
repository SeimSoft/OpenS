from PyQt6.QtCore import Qt
from opens_suite.plugins.base import OpenSPlugin
from opens_suite.properties_widget import PropertiesWidget


class PropertiesPlugin(OpenSPlugin):
    def setup(self):
        self.dock = PropertiesWidget(self.main_window)
        self.main_window.properties_dock = self.dock

        self.main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)

        view_menu = self.get_menu("&View")
        view_menu.addAction(self.dock.toggleViewAction())
