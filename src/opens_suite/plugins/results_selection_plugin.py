from opens_suite.plugins.base import OpenSPlugin
from opens_suite.results_selection_widget import ResultsSelectionWidget


class ResultsSelectionPlugin(OpenSPlugin):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.results_selection_dock = None

    def setup(self):
        self.results_selection_dock = ResultsSelectionWidget(self.main_window)
        self.main_window.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self.results_selection_dock
        )
        self.main_window.results_selection_dock = self.results_selection_dock

        # Connect refresh signals
        self.main_window.tabs.currentChanged.connect(self._sync_active_view)

        # Initial refresh
        self._sync_active_view()

    def _sync_active_view(self):
        view = self.main_window.tabs.currentWidget()
        if hasattr(view, "scene"):
            self.results_selection_dock.set_scene(view.scene())


from PyQt6.QtCore import Qt
