import os
import subprocess
import qtawesome as qta
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QToolBar
from opens_suite.plugins.base import OpenSPlugin


class CopilotPlugin(OpenSPlugin):
    def setup(self):
        from PyQt6.QtCore import QSettings

        settings = QSettings("OpenS", "OpenS")
        ai_enabled = str(settings.value("ai_features_enabled", "false")).lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if not ai_enabled:
            return

        # Load icon
        self.copilot_icon = qta.icon("mdi6.auto-fix", color="#1f1f1f")

        # Create action
        self.action = QAction(self.copilot_icon, "AI Terminal", self.main_window)
        self.action.setStatusTip("Launch AI in system terminal")
        self.action.triggered.connect(self.launch_ai)

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

    def launch_ai(self):
        # Use AppleScript to open a new terminal window and run the configured AI command
        from PyQt6.QtCore import QSettings
        settings = QSettings("OpenS", "OpenS")
        ai_cmd = settings.value("ai_terminal_command", "copilot")

        # Use AppleScript to open a new terminal window and run the command
        # This is specific to macOS.
        script = f'tell application "Terminal" to do script "{ai_cmd}"'
        cmd = f"osascript -e '{script}' -e 'tell application \"Terminal\" to activate'"
        try:
            subprocess.Popen(cmd, shell=True)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self.main_window, "Error", f"Failed to launch terminal: {e}")
