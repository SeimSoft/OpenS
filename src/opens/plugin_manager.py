from opens.plugins.library_plugin import LibraryPlugin
from opens.plugins.properties_plugin import PropertiesPlugin
from opens.plugins.analysis_plugin import AnalysisPlugin
from opens.plugins.outputs_plugin import OutputsPlugin
from opens.plugins.simulation_log_plugin import SimulationLogPlugin
from opens.plugins.calculator_plugin import CalculatorPlugin
from opens.plugins.xyce_plugin import XycePlugin
from opens.plugins.variables_plugin import VariablesPlugin
from opens.plugins.results_selection_plugin import ResultsSelectionPlugin


class PluginManager:
    def __init__(self, main_window):
        self.main_window = main_window
        self.plugins = []

    def load_plugins(self):
        # Instantiate plugins
        self.plugins = [
            LibraryPlugin(self.main_window),
            PropertiesPlugin(self.main_window),
            AnalysisPlugin(self.main_window),
            OutputsPlugin(self.main_window),
            SimulationLogPlugin(self.main_window),
            CalculatorPlugin(self.main_window),
            XycePlugin(self.main_window),
            VariablesPlugin(self.main_window),
            ResultsSelectionPlugin(self.main_window),
        ]

        # Initialize
        for plugin in self.plugins:
            plugin.setup()
