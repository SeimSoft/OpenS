from PyQt6.QtCore import Qt
from opens_suite.plugins.base import OpenSPlugin
from opens_suite.analysis_widget import AnalysisWidget


class AnalysisPlugin(OpenSPlugin):
    def setup(self):
        self.dock = AnalysisWidget(self.main_window)
        self.main_window.analysis_dock = self.dock

        self.main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)

        view_menu = self.get_menu("&View")
        view_menu.addAction(self.dock.toggleViewAction())

        self.dock.analysesChanged.connect(self._on_analyses_changed)

    def _on_analyses_changed(self):
        view = self.main_window.tabs.currentWidget()
        from opens_suite.schematic_view import SchematicView

        if isinstance(view, SchematicView):
            view.analyses = self.dock.get_all_analyses()
