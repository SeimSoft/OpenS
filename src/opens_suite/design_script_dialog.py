import os
import json
import subprocess
import sys
import numpy as np
from opens_suite.design_points import DesignPoints
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QProgressDialog,
)
from PyQt6.QtCore import Qt, QPointF, QRectF, QByteArray, QThread, pyqtSignal
from PyQt6.QtWidgets import QTextEdit, QDialogButtonBox, QApplication


class ScriptExecutionWorker(QThread):
    finished = pyqtSignal(bool, str)  # success, error_message

    def __init__(self, cmd, env, cwd):
        super().__init__()
        self.cmd = cmd
        self.env = env
        self.cwd = cwd
        self.process = None

    def run(self):
        try:
            # If cwd is empty, subprocess.Popen can fail with [Errno 2] on some systems
            # even if the command is valid. We ensure it is at least None.
            cwd_to_use = self.cwd if self.cwd else None

            self.process = subprocess.Popen(
                self.cmd,
                env=self.env,
                cwd=cwd_to_use,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = self.process.communicate()
            if self.process.returncode == 0:
                self.finished.emit(True, "")
            else:
                self.finished.emit(
                    False,
                    stderr
                    or stdout
                    or f"Process exited with code {self.process.returncode}",
                )
        except Exception as e:
            self.finished.emit(False, str(e))

    def stop(self):
        if self.process:
            try:
                self.process.terminate()
                # Give it a tiny bit of time to die gracefully
                self.process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            except Exception:
                pass


class ErrorDialog(QDialog):
    def __init__(self, title, message, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(700, 500)
        layout = QVBoxLayout(self)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlainText(message)
        # Use monospace for better readability of tracebacks
        font = self.text_edit.font()
        font.setFamily("Courier New")
        self.text_edit.setFont(font)
        layout.addWidget(self.text_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Open
        )
        # We reuse "Open" as "Copy" for simplicity or just add a custom one
        copy_btn = buttons.addButton(
            "Copy to Clipboard", QDialogButtonBox.ButtonRole.ActionRole
        )
        copy_btn.clicked.connect(self.copy_to_clipboard)

        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def copy_to_clipboard(self):
        QApplication.clipboard().setText(self.text_edit.toPlainText())
        QMessageBox.information(self, "Copied", "Error message copied to clipboard.")


class DesignScriptDialog(QDialog):
    def __init__(self, schematic_item, parent=None):
        super().__init__(parent)
        self.item = schematic_item
        self.setWindowTitle("Design Script Configuration")
        self.resize(500, 150)

        layout = QVBoxLayout(self)

        # File picker row
        file_layout = QHBoxLayout()
        file_layout.addWidget(QLabel("Jupyter Notebook Path:"))

        self.path_edit = QLineEdit()
        # Default value from the item
        current_script = self.item.parameters.get("SCRIPT", "")
        if current_script:
            self.path_edit.setText(current_script)
        file_layout.addWidget(self.path_edit)

        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse_file)
        file_layout.addWidget(self.browse_btn)

        layout.addLayout(file_layout)

        # Action buttons
        action_layout = QHBoxLayout()

        self.open_btn = QPushButton("Open Notebook")
        self.open_btn.clicked.connect(self.open_notebook)
        action_layout.addWidget(self.open_btn)

        self.apply_btn = QPushButton("Read Back Results (.json)")
        self.apply_btn.clicked.connect(self.apply_results)
        action_layout.addWidget(self.apply_btn)

        layout.addLayout(action_layout)

        # Save / Cancel
        btn_layout = QHBoxLayout()

        self.save_btn = QPushButton("Save Config")
        self.save_btn.clicked.connect(self.save_config)
        btn_layout.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        layout.addLayout(btn_layout)

        self.update_apply_button_state()
        self.path_edit.textChanged.connect(self.update_apply_button_state)

    def browse_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Select Jupyter Notebook",
            "",
            "Jupyter Notebook (*.ipynb);;All Files (*)",
        )
        if path:
            self.path_edit.setText(path)

    def update_apply_button_state(self):
        script_path = self.path_edit.text()
        if not script_path:
            self.apply_btn.setEnabled(False)
            return

        json_path = os.path.splitext(script_path)[0] + ".json"
        abs_json_path = self.get_absolute_path(json_path)
        self.apply_btn.setEnabled(os.path.exists(abs_json_path))

    def get_absolute_path(self, path):
        if not path:
            return ""
        if os.path.isabs(path):
            return path
        try:
            view = self.item.scene().views()[0]
            if hasattr(view, "filename") and view.filename:
                return os.path.abspath(
                    os.path.join(os.path.dirname(view.filename), path)
                )
        except Exception:
            pass
        return os.path.abspath(path)

    @staticmethod
    def get_absolute_path_for_item(item, path):
        if not path:
            return ""
        if os.path.isabs(path):
            return path
        try:
            view = item.scene().views()[0]
            if hasattr(view, "filename") and view.filename:
                return os.path.abspath(
                    os.path.join(os.path.dirname(view.filename), path)
                )
        except Exception:
            pass
        return os.path.abspath(path)

    @staticmethod
    def open_notebook(item):
        script_path = item.parameters.get("SCRIPT", "")
        is_stimuli = item.svg_path and item.svg_path.lower().endswith(
            "stimuli_generator.svg"
        )
        if not script_path:
            # Default fallbacks if not defined
            script_path = (
                "stimuli_generator.ipynb" if is_stimuli else "design_script.ipynb"
            )

        abs_script_path = DesignScriptDialog.get_absolute_path_for_item(
            item, script_path
        )

        # If does not exist, create using template
        if not os.path.exists(abs_script_path):
            try:
                # Choose template
                template_name = (
                    "stimuli_generator_template.ipynb"
                    if is_stimuli
                    else "design_script_template.ipynb"
                )

                template_path = os.path.join(
                    os.path.dirname(__file__),
                    "templates",
                    template_name,
                )
                if os.path.exists(template_path):
                    with open(template_path, "r") as f:
                        nb_data = json.load(f)

                    # Target JSON filename matches the notebook name
                    target_json = (
                        os.path.splitext(os.path.basename(abs_script_path))[0] + ".json"
                    )

                    # Search for dps.save(...) and update it
                    import re

                    for cell in nb_data.get("cells", []):
                        if cell.get("cell_type") == "code":
                            source = cell.get("source", [])
                            # Source can be a list of strings or a single string
                            if isinstance(source, list):
                                new_source = []
                                for line in source:
                                    # Regex to replace filename in dps.save("...", ...)
                                    new_line = re.sub(
                                        r'(dps\.save\(")([^"]*)(")',
                                        rf"\1{target_json}\3",
                                        line,
                                    )
                                    new_source.append(new_line)
                                cell["source"] = new_source
                            elif isinstance(source, str):
                                cell["source"] = re.sub(
                                    r'(dps\.save\(")([^"]*)(")',
                                    rf"\1{target_json}\3",
                                    source,
                                )

                    with open(abs_script_path, "w") as f:
                        json.dump(nb_data, f, indent=1)
                else:
                    # Fallback to basic empty notebook if template missing
                    empty_nb = {
                        "cells": [],
                        "metadata": {},
                        "nbformat": 4,
                        "nbformat_minor": 5,
                    }
                    with open(abs_script_path, "w") as f:
                        json.dump(empty_nb, f)
            except Exception as e:
                QMessageBox.critical(
                    None, "Error", f"Failed to create notebook from template: {e}"
                )
                return

        # Use editor_command from settings
        from PyQt6.QtCore import QSettings

        settings = QSettings("OpenS", "OpenS")
        editor_cmd = settings.value("editor_command", "code '%s'")

        try:
            import shlex

            if "%s" in editor_cmd:
                cmd_str = editor_cmd.replace("%s", abs_script_path)
            else:
                cmd_str = f"{editor_cmd} '{abs_script_path}'"

            args = shlex.split(cmd_str)
            subprocess.Popen(args)
        except Exception as e:
            QMessageBox.critical(
                None,
                "Error",
                f"Failed to open notebook:\nCommand: {editor_cmd}\nError: {e}",
            )

    @staticmethod
    def execute_and_apply(item):
        script_path = item.parameters.get("SCRIPT", "")
        if not script_path:
            QMessageBox.warning(
                None, "Missing Path", "No script path defined for this item."
            )
            return

        # Resolve absolute path very robustly
        abs_script_path = ""
        try:
            if os.path.isabs(script_path):
                abs_script_path = script_path
            else:
                # Try to resolve relative to current schematic
                view = item.scene().views()[0]
                if hasattr(view, "filename") and view.filename:
                    abs_script_path = os.path.abspath(
                        os.path.join(os.path.dirname(view.filename), script_path)
                    )
                else:
                    abs_script_path = os.path.abspath(script_path)
        except Exception:
            abs_script_path = os.path.abspath(script_path)

        if not abs_script_path or not os.path.exists(abs_script_path):
            QMessageBox.warning(
                None, "Not Found", f"Notebook file not found at:\n{abs_script_path}"
            )
            return

        # Prepare environment
        # Find the 'src' directory (parent of 'opens' package)
        # This file is at src/opens/design_script_dialog.py, so we go up two levels.
        src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        notebook_dir = os.path.dirname(abs_script_path)

        env = os.environ.copy()
        pythonpath_entries = [src_path, notebook_dir]
        if "PYTHONPATH" in env:
            env["PYTHONPATH"] = os.pathsep.join(
                pythonpath_entries + [env["PYTHONPATH"]]
            )
        else:
            env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)

        # Prepare command
        cmd = [
            sys.executable,
            "-m",
            "jupyter",
            "nbconvert",
            "--to",
            "notebook",
            "--execute",
            "--inplace",
            "--ExecutePreprocessor.timeout=None",
            "--ExecutePreprocessor.kernel_name=python3",
            abs_script_path,
        ]

        # Create progress dialog
        progress = QProgressDialog(
            f"Executing {os.path.basename(abs_script_path)}...", "Abort", 0, 0, None
        )
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setWindowTitle("Design Script")
        progress.setMinimumDuration(0)
        progress.show()

        worker = ScriptExecutionWorker(cmd, env, notebook_dir)

        def on_finished(success, error_msg):
            progress.close()
            if success:
                # Apply JSON results
                json_path = os.path.splitext(abs_script_path)[0] + ".json"
                if os.path.exists(json_path):
                    DesignScriptDialog.apply_json_to_item_scene(item, json_path)
                else:
                    QMessageBox.warning(
                        None,
                        "Missing Results",
                        f"Execution finished but no result file found at:\n{json_path}",
                    )
            else:
                cwd_display = notebook_dir if notebook_dir else "<None>"
                debug_info = f"\n\nDebug Info:\n- Interpreter: {sys.executable}\n- PYTHONPATH: {env.get('PYTHONPATH')}\n- CWD: {cwd_display}"
                full_msg = f"Failed to execute notebook:\n\n{error_msg}{debug_info}"

                dlg = ErrorDialog("Execution Error", full_msg)
                dlg.exec()

        worker.finished.connect(on_finished)
        progress.canceled.connect(worker.stop)

        worker.start()
        # Keep a reference to prevent garbage collection
        item._script_worker = worker

    @staticmethod
    def apply_json_to_item_scene(item, json_path):
        if not os.path.exists(json_path):
            return 0

        try:
            with open(json_path, "r") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(None, "Error", f"Failed to parse JSON: {e}")
            return 0

        scene = item.scene()
        items_by_name = {}
        for it in scene.items():
            if hasattr(it, "name") and it.name:
                items_by_name[it.name] = it

        # Access Variables dock
        main_window = None
        if scene.views():
            view = scene.views()[0]
            main_window = view.window()

        variables_dock = getattr(main_window, "variables_dock", None)
        current_variables = []
        if variables_dock:
            current_variables = variables_dock.get_variables()

        applied_count = 0
        vars_updated = False
        details = []

        for key, value in data.items():
            # Skip internal keys
            if key in ["runset", "t"]:
                continue

            if isinstance(value, (int, float, np.number)):
                formatted_value = DesignPoints._format_si(value)
            else:
                formatted_value = str(value)

            # 1. Update variables if name matches
            if variables_dock:
                var_match = False
                for var in current_variables:
                    if var["name"] == key:
                        var["value"] = formatted_value
                        var_match = True
                        vars_updated = True
                        applied_count += 1
                        details.append(f"Variable '{key}' -> {formatted_value}")
                        break
                if var_match:
                    continue

            # 2. Update component parameters (format: CompName.ParamName)
            parts = key.split(".")
            if len(parts) == 2:
                comp_name, param_name = parts
                if comp_name in items_by_name:
                    target = items_by_name[comp_name]
                    target.set_parameter(param_name, formatted_value)
                    applied_count += 1
                    details.append(
                        f"Item '{comp_name}.{param_name}' -> {formatted_value}"
                    )
                else:
                    # Maybe it's a global search for parameter name?
                    # For now we only support Comp.Param
                    pass
            else:
                # If only one part, maybe it's a component name and we update its 'Value'?
                if key in items_by_name:
                    target = items_by_name[key]
                    target.set_parameter("Value", formatted_value)
                    applied_count += 1
                    details.append(f"Item '{key}.Value' -> {formatted_value}")

        is_stimuli = item.svg_path and item.svg_path.lower().endswith(
            "stimuli_generator.svg"
        )
        has_runset = "runset" in data

        if vars_updated and variables_dock:
            variables_dock.set_variables(current_variables)

        # Trigger visual/connectivity updates
        if scene.views():
            view = scene.views()[0]
            if hasattr(view, "recalculate_connectivity"):
                view.recalculate_connectivity()

        scene.update()

        # Build message
        detail_msg = "\n".join(details)
        if is_stimuli:
            msg = "Stimuli runset updated." if has_runset else ""
            if applied_count > 0:
                msg += f"\n\nUpdates:\n{detail_msg}"
            if not msg:
                msg = "No stimuli or parameters found in JSON."
            QMessageBox.information(None, "Stimuli Generator", msg)
        else:
            if applied_count > 0:
                QMessageBox.information(
                    None,
                    "Design Script",
                    f"Applied {applied_count} parameters:\n\n{detail_msg}",
                )
            elif not has_runset:
                QMessageBox.information(
                    None,
                    "Design Script",
                    "Execution finished, but no parameters were matched to schematic items or variables.",
                )
            else:
                QMessageBox.information(
                    None, "Design Script", "Custom netlist snippet (runset) updated."
                )

        return applied_count

    def apply_results(self):
        script_path = self.path_edit.text()
        json_path = os.path.splitext(script_path)[0] + ".json"
        abs_json_path = self.get_absolute_path(json_path)

        if not os.path.exists(abs_json_path):
            QMessageBox.warning(
                self, "Not Found", f"Result file {json_path} not found."
            )
            return

        DesignScriptDialog.apply_json_to_item_scene(self.item, abs_json_path)
        self.update_apply_button_state()

    def save_config(self):
        self.item.set_parameter("SCRIPT", self.path_edit.text())
        self.accept()


class StimuliGeneratorDialog(DesignScriptDialog):
    def __init__(self, schematic_item, parent=None):
        super().__init__(schematic_item, parent)
        self.setWindowTitle("Stimuli Generator Configuration")
        self.apply_btn.setText("Apply Stimuli (from .json)")
        self.apply_btn.setToolTip(
            "Reads the generated JSON. Note: Stimuli with key 'runset' are applied automatically during netlisting."
        )
