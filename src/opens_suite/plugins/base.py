from PyQt6.QtWidgets import QToolBar


class OpenSPlugin:
    def __init__(self, main_window):
        self.main_window = main_window

    def setup(self):
        """Called to initialize the plugin and integrate it with the main window."""
        pass

    def get_menu(self, title):
        """Helper to get or create a menu by title."""
        for action in self.main_window.menuBar().actions():
            if action.text().replace("&", "") == title.replace("&", ""):
                return action.menu()
        return self.main_window.menuBar().addMenu(title)

    def get_toolbar(self, title):
        """Helper to get or create a toolbar by title."""
        for tb in self.main_window.findChildren(QToolBar):
            if tb.windowTitle() == title:
                return tb
        tb = QToolBar(title)
        self.main_window.addToolBar(tb)
        return tb
