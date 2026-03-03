from PyQt6.QtCore import Qt
from opens.plugins.base import OpenSPlugin
from opens.library import LibraryWidget


class LibraryPlugin(OpenSPlugin):
    def setup(self):
        self.dock = LibraryWidget(self.main_window)
        # Attach to main window for existing cross-references
        self.main_window.library_dock = self.dock

        self.main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)

        view_menu = self.get_menu("&View")
        view_menu.addAction(self.dock.toggleViewAction())
