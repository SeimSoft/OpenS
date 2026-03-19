import os
import subprocess
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QToolBar
from opens_suite.plugins.base import OpenSPlugin


class CopilotPlugin(OpenSPlugin):
    def setup(self):
        # Load icon
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "assets", "icons", "copilot.svg"
        )
        self.copilot_icon = QIcon(icon_path)

        # Create action
        self.action = QAction(self.copilot_icon, "GitHub Copilot", self.main_window)
        self.action.setStatusTip("Launch GitHub Copilot in system terminal")
        self.action.triggered.connect(self.launch_copilot)

        # Add to Simulation Toolbar
        toolbars = self.main_window.findChildren(QToolBar)
        sim_toolbar = next(
            (tb for tb in toolbars if tb.windowTitle() == "Simulation Toolbar"), None
        )
        if sim_toolbar:
            sim_toolbar.addAction(self.action)
        else:
            # Fallback: create a new toolbar if not found
            self.toolbar = QToolBar("Extensions")
            self.main_window.addToolBar(self.toolbar)
            self.toolbar.addAction(self.action)

    def launch_copilot(self):
        # Use AppleScript to open a new terminal window and run copilot
        # This is specific to macOS.
        script = 'tell application "Terminal" to do script "copilot"'
        cmd = f"osascript -e '{script}' -e 'tell application \"Terminal\" to activate'"
        try:
            subprocess.Popen(cmd, shell=True)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self.main_window, "Error", f"Failed to launch terminal: {e}")
