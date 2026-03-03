from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLineEdit,
    QLabel,
    QTabWidget,
    QWidget,
    QFormLayout,
    QDialogButtonBox,
    QHBoxLayout,
    QPushButton,
    QFileDialog,
    QMessageBox,
)
from PyQt6.QtCore import QSettings
import subprocess
import os


class ModelEditorDialog(QDialog):
    """Dialog to edit `.model` symbol parameters.

    The dialog contains a shared ModelName field and three tabs: DIODE, NMOS, PMOS.
    When accepted, it exposes .modelname, .type and .args properties.
    """

    def __init__(self, parent=None, initial=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Model")
        self.resize(420, 320)

        self.modelname_edit = QLineEdit()

        # Tabs
        self.tabs = QTabWidget()
        self.diode_tab = QWidget()
        self.nmos_tab = QWidget()
        self.pmos_tab = QWidget()
        self.python_tab = QWidget()

        # Build tab contents
        self._build_diode_tab()
        self._build_nmos_tab()
        self._build_pmos_tab()
        self._build_python_tab()

        # Add tabs
        self.tabs.addTab(self.diode_tab, "D (DIODE)")
        self.tabs.addTab(self.nmos_tab, "NMOS")
        self.tabs.addTab(self.pmos_tab, "PMOS")
        self.tabs.addTab(self.python_tab, "PYTHON")

        # Buttons
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Model Name:"))
        layout.addWidget(self.modelname_edit)
        layout.addWidget(self.tabs)
        layout.addWidget(self.buttons)

        self.setLayout(layout)

        # Fill initial values if provided
        if initial:
            # Case-insensitive access for incoming parameter dict
            def _get(key, default=""):
                for k, v in initial.items():
                    if k.lower() == key.lower():
                        return v
                return default

            self.modelname_edit.setText(_get("MODELNAME", ""))

            # Parse ARGS into dict and populate fields depending on type
            args_raw = _get("ARGS", "")
            args_map = self._parse_args_to_dict(args_raw)

            tval = _get("TYPE", "NMOS").strip().upper()
            if tval in ("DIODE", "D"):
                self.tabs.setCurrentWidget(self.diode_tab)
                # populate diode fields
                self.d_is.setText(args_map.get("IS", self.d_is.text()))
                self.d_n.setText(args_map.get("N", self.d_n.text()))
                self.d_rs.setText(args_map.get("RS", self.d_rs.text()))
                self.d_cjo.setText(args_map.get("CJO", self.d_cjo.text()))
                self.d_m.setText(args_map.get("M", self.d_m.text()))
                self.d_tt.setText(args_map.get("TT", self.d_tt.text()))
            elif tval == "PMOS":
                self.tabs.setCurrentWidget(self.pmos_tab)
                self.p_level.setText(args_map.get("LEVEL", self.p_level.text()))
                self.p_vto.setText(args_map.get("VTO", self.p_vto.text()))
                self.p_kp.setText(args_map.get("KP", self.p_kp.text()))
                self.p_lambda.setText(args_map.get("LAMBDA", self.p_lambda.text()))
                self.p_cgso.setText(args_map.get("CGSO", self.p_cgso.text()))
                self.p_cgdo.setText(args_map.get("CGDO", self.p_cgdo.text()))
                self.p_cbd.setText(args_map.get("CBD", self.p_cbd.text()))
            elif tval in ("PYTHON", "PY"):
                self.tabs.setCurrentWidget(self.python_tab)
                # Populate python-specific fields
                self.py_module.setText(
                    args_map.get("PYTHON_MODULE", self.py_module.text())
                )
                self.py_class.setText(
                    args_map.get("PYTHON_CLASS", self.py_class.text())
                )
                self.py_path.setText(args_map.get("PYTHON_PATH", self.py_path.text()))
            else:
                self.tabs.setCurrentWidget(self.nmos_tab)
                self.n_level.setText(args_map.get("LEVEL", self.n_level.text()))
                self.n_vto.setText(args_map.get("VTO", self.n_vto.text()))
                self.n_kp.setText(args_map.get("KP", self.n_kp.text()))
                self.n_lambda.setText(args_map.get("LAMBDA", self.n_lambda.text()))
                self.n_cgso.setText(args_map.get("CGSO", self.n_cgso.text()))
                self.n_cgdo.setText(args_map.get("CGDO", self.n_cgdo.text()))
                self.n_cbd.setText(args_map.get("CBD", self.n_cbd.text()))

    def _build_diode_tab(self):
        form = QFormLayout()
        # Typical diode parameters
        self.d_is = QLineEdit("1e-14")
        self.d_n = QLineEdit("1")
        self.d_rs = QLineEdit("0")
        self.d_cjo = QLineEdit("1p")
        self.d_m = QLineEdit("0.5")
        self.d_tt = QLineEdit("1n")

        form.addRow("IS:", self.d_is)
        form.addRow("N:", self.d_n)
        form.addRow("RS:", self.d_rs)
        form.addRow("CJO:", self.d_cjo)
        form.addRow("M:", self.d_m)
        form.addRow("TT:", self.d_tt)

        self.diode_tab.setLayout(form)

    def _build_nmos_tab(self):
        form = QFormLayout()
        # Use defaults similar to previous ARGS
        self.n_level = QLineEdit("1")
        self.n_vto = QLineEdit("2.5")
        self.n_kp = QLineEdit("0.5")
        self.n_lambda = QLineEdit("0.02")
        self.n_cgso = QLineEdit("100p")
        self.n_cgdo = QLineEdit("10p")
        self.n_cbd = QLineEdit("50p")

        form.addRow("LEVEL:", self.n_level)
        form.addRow("VTO:", self.n_vto)
        form.addRow("KP:", self.n_kp)
        form.addRow("LAMBDA:", self.n_lambda)
        form.addRow("CGSO:", self.n_cgso)
        form.addRow("CGDO:", self.n_cgdo)
        form.addRow("CBD:", self.n_cbd)

        self.nmos_tab.setLayout(form)

    def _build_pmos_tab(self):
        form = QFormLayout()
        # Start with same defaults but inverted sign where typical
        self.p_level = QLineEdit("1")
        self.p_vto = QLineEdit("-2.5")
        self.p_kp = QLineEdit("0.5")
        self.p_lambda = QLineEdit("0.02")
        self.p_cgso = QLineEdit("100p")
        self.p_cgdo = QLineEdit("10p")
        self.p_cbd = QLineEdit("50p")

        form.addRow("LEVEL:", self.p_level)
        form.addRow("VTO:", self.p_vto)
        form.addRow("KP:", self.p_kp)
        form.addRow("LAMBDA:", self.p_lambda)
        form.addRow("CGSO:", self.p_cgso)
        form.addRow("CGDO:", self.p_cgdo)
        form.addRow("CBD:", self.p_cbd)

        self.pmos_tab.setLayout(form)

    def _build_python_tab(self):
        form = QFormLayout()

        self.py_module = QLineEdit("")
        self.py_class = QLineEdit("")
        self.py_path = QLineEdit(".")

        browse = QPushButton("Browse")

        def _on_browse():
            d = QFileDialog.getExistingDirectory(self, "Select Python Path", ".")
            if d:
                self.py_path.setText(d)

        browse.clicked.connect(_on_browse)

        edit_button = QPushButton("Edit in Editor")

        def _on_edit():
            path = self.py_path.text().strip()
            if not path:
                return

            # Resolve relative path if possible?
            # For now just use as is or absolute
            abs_path = os.path.abspath(path)

            settings = QSettings("OpenS", "OpenS")
            cmd_template = settings.value("editor_command", "code '%s'")

            if "%s" in cmd_template:
                cmd = cmd_template.replace("%s", abs_path)
            else:
                cmd = f"{cmd_template} {abs_path}"

            try:
                # Use shell=True to support commands like "code '%s'" or aliases
                subprocess.Popen(cmd, shell=True)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to open editor: {e}")

        edit_button.clicked.connect(_on_edit)

        # Path row: use a horizontal layout
        h = QHBoxLayout()
        h.addWidget(self.py_path)
        h.addWidget(browse)
        h.addWidget(edit_button)

        form.addRow("Python Module:", self.py_module)
        form.addRow("Python Class:", self.py_class)
        form.addRow("Python Path:", h)

        self.python_tab.setLayout(form)

    def get_result(self):
        modelname = self.modelname_edit.text().strip() or "MODEL1"
        current = self.tabs.currentWidget()

        if current is self.diode_tab:
            typ = "D"  # Use standard spice 'D' for diode
            args = (
                f"(IS={self.d_is.text()} N={self.d_n.text()} RS={self.d_rs.text()} "
                f"CJO={self.d_cjo.text()} M={self.d_m.text()} TT={self.d_tt.text()})"
            )
        elif current is self.pmos_tab:
            typ = "PMOS"
            args = (
                f"(LEVEL={self.p_level.text()} VTO={self.p_vto.text()} KP={self.p_kp.text()} "
                f"LAMBDA={self.p_lambda.text()} CGSO={self.p_cgso.text()} CGDO={self.p_cgdo.text()} "
                f"CBD={self.p_cbd.text()})"
            )
        elif current is self.python_tab:
            typ = "python"
            # Quote strings to produce: (python_module = "mod" python_class = "cls" python_path=".")
            mod = self.py_module.text().strip()
            cls = self.py_class.text().strip()
            path = self.py_path.text().strip()
            args = (
                f'(python_module = "{mod}" '
                f'python_class = "{cls}" '
                f'python_path="{path}")'
            )
        else:
            typ = "NMOS"
            args = (
                f"(LEVEL={self.n_level.text()} VTO={self.n_vto.text()} KP={self.n_kp.text()} "
                f"LAMBDA={self.n_lambda.text()} CGSO={self.n_cgso.text()} CGDO={self.n_cgdo.text()} "
                f"CBD={self.n_cbd.text()})"
            )

        return {"MODELNAME": modelname, "TYPE": typ, "ARGS": args}

    def _parse_args_to_dict(self, args_raw: str) -> dict:
        """Parse an ARGS string like '(LEVEL=1 VTO=2.5 ...)' into a dict.

        Accepts versions with or without surrounding parentheses. Keys are
        returned upper-cased.
        """
        out = {}
        if not args_raw:
            return out

        s = args_raw.strip()
        if s.startswith("(") and s.endswith(")"):
            s = s[1:-1]

        # Use regex to find key=value pairs. Value may be quoted and may contain
        # characters (but not closing quote). Accept both 'KEY=VALUE' and
        # 'KEY = "value with spaces"' styles.
        import re

        pattern = re.compile(r"(\w+)\s*=\s*(\".*?\"|\S+)")
        for m in pattern.finditer(s):
            k = m.group(1).upper()
            v = m.group(2)
            # Strip surrounding quotes if present
            if v.startswith('"') and v.endswith('"') and len(v) >= 2:
                v = v[1:-1]
            out[k] = v

        return out
