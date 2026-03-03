import os
from PyQt6.QtCore import Qt
from opens.plugins.base import OpenSPlugin
from opens.outputs_widget import OutputsWidget


class OutputsPlugin(OpenSPlugin):
    def setup(self):
        self.dock = OutputsWidget()
        self.main_window.outputs_dock = self.dock

        self.main_window.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea, self.dock
        )

        # Attach logic directly pointing to existing methods
        self.dock.expressionsChanged.connect(self._on_outputs_changed)

        # When tab changes, connect to the new view
        self.main_window.tabs.currentChanged.connect(self._on_tab_changed)
        self._on_tab_changed()

    def _on_tab_changed(self):
        view = self.main_window.tabs.currentWidget()
        from opens.schematic_view import SchematicView

        if isinstance(view, SchematicView):
            try:
                view.simulationFinished.disconnect(self._evaluate_all)
            except TypeError:
                pass
            view.simulationFinished.connect(self._evaluate_all)

            # Initial restore if view has outputs
            if hasattr(view, "outputs"):
                self.dock.blockSignals(True)
                self.dock.restore_expressions(view.outputs)
                self.dock.blockSignals(False)

    def _evaluate_all(self):
        view = self.main_window.tabs.currentWidget()
        if not view:
            return

        filename = getattr(view, "filename", None)
        if filename:
            sim_dir = os.path.join(os.path.dirname(filename), "simulation")
            base = os.path.splitext(os.path.basename(filename))[0]
            raw_path = os.path.join(sim_dir, f"{base}.raw")
            if os.path.exists(raw_path):
                self.dock.evaluate_all(raw_path)

    def _on_outputs_changed(self):
        view = self.main_window.tabs.currentWidget()
        from opens.schematic_view import SchematicView

        if isinstance(view, SchematicView):
            view.outputs = self.dock.get_expressions_data()
