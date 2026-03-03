import os
import traceback
import numpy as np
from PyQt6.QtWidgets import (
    QMainWindow,
    QVBoxLayout,
    QTextEdit,
    QLabel,
    QMessageBox,
    QDialog,
    QSplitter,
    QTreeView,
    QWidget,
    QToolBar,
    QDockWidget,
)
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QAction, QIcon
from PyQt6.QtCore import Qt, QModelIndex, pyqtSignal
from opens.spice_parser import SpiceRawParser
from opens.waveform_viewer import WaveformViewer


class CalculatorDialog(QMainWindow):
    sendToOutputsRequested = pyqtSignal(str)
    probeRequested = pyqtSignal()

    def __init__(self, raw_path, parent=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.raw_path = raw_path
        self.all_plots = {}
        self._load_data()
        self.viewer = None  # Waveform viewer window

        self.probe_icon = QIcon(
            os.path.join(os.path.dirname(__file__), "assets", "icons", "probe.svg")
        )
        self._setup_ui()
        self._populate_signals()

    def _load_data(self):
        if not self.raw_path or not os.path.exists(self.raw_path):
            return

        parser = SpiceRawParser(self.raw_path)
        self.all_plots = parser.parse() or {}

    def refresh(self):
        self._load_data()
        self._populate_signals()

    def _setup_ui(self):
        self.setWindowTitle("Simulation Calculator")
        self.resize(900, 600)

        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)

        self.send_to_outputs_action = QAction("📤 Send to Outputs", self)
        self.send_to_outputs_action.setToolTip(
            "Add this expression to the Output Expressions dock"
        )
        self.send_to_outputs_action.triggered.connect(self._send_to_outputs)
        toolbar.addAction(self.send_to_outputs_action)

        self.eval_action = QAction("▶️ Evaluate", self)
        self.eval_action.setToolTip("Execute the Python script")
        self.eval_action.triggered.connect(self.evaluate)
        toolbar.addAction(self.eval_action)

        self.probe_action = QAction(self.probe_icon, "Probe Schematic", self)
        self.probe_action.setToolTip("Click a net in the schematic to insert it here")
        self.probe_action.triggered.connect(self.probeRequested.emit)
        toolbar.addAction(self.probe_action)

        self.clear_action = QAction("🧹 Clear", self)
        self.clear_action.setToolTip("Clear the python script")
        toolbar.addAction(self.clear_action)

        # Help action to show available functions/variables
        self.help_action = QAction("❓ Help", self)
        self.help_action.setToolTip("Show available functions and variables")
        self.help_action.triggered.connect(self._show_help_dialog)
        toolbar.addAction(self.help_action)

        self.addToolBar(toolbar)

        # Central widget: script editor
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(8, 8, 8, 8)

        title_label = QLabel("Python Script:")
        title_label.setStyleSheet("font-size: 12pt; font-weight: bold;")
        central_layout.addWidget(title_label)

        self.script_edit = QTextEdit()
        self.script_edit.setAcceptRichText(False)
        self.script_edit.setPlaceholderText(
            "# Example:\nplot(t, dB(vf('vout')))\n\n# Or just:\nvt('v1')"
        )
        from opens.syntax_highlighter import apply_dark_plus_theme

        apply_dark_plus_theme(self.script_edit)
        central_layout.addWidget(self.script_edit)

        self.setCentralWidget(central)
        self._setup_result_dock()  # Add result dock
        self._setup_signal_browser()

    def _setup_result_dock(self):
        self.result_edit = QTextEdit()
        self.result_edit.setReadOnly(True)
        self.result_edit.setPlaceholderText("Scalar results will appear here...")

        dock = QDockWidget("Results", self)
        dock.setWidget(self.result_edit)
        dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

    def insert_expression(self, expr):
        """Insert a string into the script editor at the current cursor position."""
        self.script_edit.insertPlainText(expr + "\n")
        self.script_edit.ensureCursorVisible()
        self.activateWindow()
        self.raise_()

    def _setup_signal_browser(self):
        # Signal Browser as a dock widget on the right
        browser_container = QWidget()
        browser_layout = QVBoxLayout(browser_container)
        browser_layout.setContentsMargins(4, 4, 4, 4)
        browser_layout.addWidget(QLabel("Signal Browser:"))
        self.signal_tree = QTreeView()
        self.signal_model = QStandardItemModel()
        self.signal_model.setHorizontalHeaderLabels(["Analysis / Signal"])
        self.signal_tree.setModel(self.signal_model)
        self.signal_tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.signal_tree.setHeaderHidden(False)
        self.signal_tree.doubleClicked.connect(self._on_signal_double_clicked)
        browser_layout.addWidget(self.signal_tree)

        dock = QDockWidget("Signal Browser", self)
        dock.setWidget(browser_container)
        dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def _send_to_outputs(self):
        script = self.script_edit.toPlainText().strip()
        if script:
            self.sendToOutputsRequested.emit(script)

    def _show_help_dialog(self):
        """Show a dialog listing available functions and variables from the current data scope."""
        scope = self._create_scope()
        keys = sorted(scope.keys())

        help_lines = [
            "Available functions and variables:",
            "",
        ]
        for k in keys:
            help_lines.append(k)

        help_text = "\n".join(help_lines)

        dlg = QDialog(self)
        dlg.setWindowTitle("Calculator Help")
        dlg.resize(500, 400)
        layout = QVBoxLayout(dlg)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(help_text)
        layout.addWidget(te)
        dlg.exec()

    def _populate_signals(self):
        self.signal_model.clear()
        self.signal_model.setHorizontalHeaderLabels(["Analysis / Signal"])

        for plot_name, signals in self.all_plots.items():
            plot_item = QStandardItem(plot_name)
            plot_item.setData(plot_name, Qt.ItemDataRole.UserRole)

            for sig_name in sorted(signals.keys()):
                sig_item = QStandardItem(sig_name)
                sig_item.setData(sig_name, Qt.ItemDataRole.UserRole)
                plot_item.appendRow(sig_item)

            self.signal_model.appendRow(plot_item)

        self.signal_tree.expandAll()

    def _on_signal_double_clicked(self, index: QModelIndex):
        item = self.signal_model.itemFromIndex(index)
        if not item or item.parent() is None:
            return  # It's a plot name, not a signal

        plot_name = item.parent().data(Qt.ItemDataRole.UserRole)
        sig_name = item.data(Qt.ItemDataRole.UserRole)

        # Use new generic signal types
        is_ac = "AC" in plot_name
        is_op = "Operating Point" in plot_name
        is_dc = "DC" in plot_name

        if is_op:
            text = f"sop('{sig_name}')"
        elif is_ac:
            text = f"sf('{sig_name}')"
        elif is_dc:
            text = f"sdc('{sig_name}')"
        else:
            text = f"st('{sig_name}')"

        if is_op:
            self.insert_expression(text)
            return

        full_expr = f'plot({text}, label="{text}")'
        self.insert_expression(full_expr)

    def evaluate(self):
        script = self.script_edit.toPlainText().strip()
        if not script:
            return

        # Ensure viewer is ready
        if not self.viewer or self.viewer.isHidden():
            self.viewer = WaveformViewer(self)
            self.viewer.show()

        self.viewer.clear()
        scope = self._create_scope()

        try:
            # Use scope as both globals and locals to ensure refs are found
            # and __builtins__ is handled by eval itself
            result = eval(script, scope)
            if isinstance(result, np.ndarray):
                # Auto-plot if result is an array
                x_axis = scope["t"] if "vt" in script or "it" in script else scope["f"]

                # If this is an AC complex result plotted against frequency, show Bode (dB + phase)
                if (
                    np.array_equal(x_axis, scope.get("f", np.array([])))
                    and np.iscomplexobj(result)
                    and len(x_axis) == len(result)
                ):
                    self.viewer.bode(result, label=script)
                else:
                    self.viewer.plot(x_axis, result, label=script)

            self.viewer.show()
            self.viewer.raise_()

            # Handle scalar result for the result dock
            if result is not None:
                self._display_result(script, result)

        except Exception as e:
            # If eval fails, try exec for multi-line scripts
            try:
                # Helper to execute multi-line and get last value
                import ast

                def exec_get_last(code, scope):
                    tree = ast.parse(code)
                    if not tree.body:
                        return None
                    last_node = tree.body[-1]
                    if isinstance(last_node, ast.Expr):
                        if len(tree.body) > 1:
                            exec_body = ast.Module(body=tree.body[:-1], type_ignores=[])
                            exec(
                                compile(exec_body, "<string>", "exec"),
                                scope,
                            )
                        eval_expr = ast.Expression(body=last_node.value)
                        return eval(
                            compile(eval_expr, "<string>", "eval"),
                            scope,
                        )
                    else:
                        exec(code, scope)
                        return None

                result = exec_get_last(script, scope)

                self.viewer.show()
                self.viewer.raise_()

                if result is not None:
                    self._display_result(script, result)

            except Exception as e2:
                QMessageBox.critical(
                    self, "Execution Error", f"Error: {e2}\n{traceback.format_exc()}"
                )

    def _display_result(self, script, result):
        # We only want to show scalars (or small objects) in the dock
        from opens.design_points import DesignPoints

        if isinstance(result, (int, float, np.number, complex)):
            val_str = ""
            if isinstance(result, complex):
                val_str = f"{DesignPoints._format_si(result.real)} + j{DesignPoints._format_si(result.imag)}"
            else:
                val_str = DesignPoints._format_si(float(result))

            # Simple one-liner script display
            short_script = script.split("\n")[-1]
            if len(short_script) > 30:
                short_script = short_script[:27] + "..."

            self.result_edit.append(f"<b>{short_script}</b> = {val_str}")
        elif isinstance(result, np.ndarray) and result.size == 1:
            val_float = float(result.item())
            self.result_edit.append(
                f"<b>{script}</b> = {DesignPoints._format_si(val_float)}"
            )

    def _create_scope(self):
        # Default plots
        tran_plot = None
        ac_plot = None
        op_plot = None
        dc_plot = None

        for name, data in self.all_plots.items():
            if "Transient" in name:
                tran_plot = data
            elif "AC Analysis" in name:
                ac_plot = data
            elif "Operating Point" in name:
                op_plot = data
            elif "DC transfer characteristic" in name:
                dc_plot = data

        # Fallbacks
        if not tran_plot and self.all_plots:
            candidates = [
                p for n, p in self.all_plots.items() if "Operating Point" not in n
            ]
            if candidates:
                tran_plot = sorted(
                    candidates, key=lambda x: len(next(iter(x.values()))), reverse=True
                )[0]

        t = np.array([])
        f_vec = np.array([])

        if tran_plot:
            for k in tran_plot.keys():
                if k.lower() == "time":
                    t = np.array(tran_plot[k])
                    break
        if ac_plot:
            for k in ac_plot.keys():
                if k.lower() == "frequency":
                    f_vec = np.array(ac_plot[k]).real
                    break

        from opens.spice_parser import SpiceRawParser

        def vt(name, plot=None):
            ds = self.all_plots.get(plot, tran_plot) if plot else tran_plot
            val = SpiceRawParser.find_signal(ds, name, type_hint="v")
            if val is None:
                raise ValueError(f"Transient signal '{name}' not found.")
            return np.array(val)

        def it(name, plot=None):
            ds = self.all_plots.get(plot, tran_plot) if plot else tran_plot
            val = SpiceRawParser.find_signal(ds, name, type_hint="i")
            if val is None:
                raise ValueError(f"Transient current '{name}' not found.")
            return np.array(val)

        def vf(name, plot=None):
            ds = self.all_plots.get(plot, ac_plot) if plot else ac_plot
            val = SpiceRawParser.find_signal(ds, name, type_hint="v")
            if val is None:
                raise ValueError(f"AC signal '{name}' not found.")
            return np.array(val)

        def ifc(name, plot=None):
            ds = self.all_plots.get(plot, ac_plot) if plot else ac_plot
            val = SpiceRawParser.find_signal(ds, name, type_hint="i")
            if val is None:
                raise ValueError(f"AC current '{name}' not found.")
            return np.array(val)

        def op(name, plot=None):
            ds = self.all_plots.get(plot, op_plot) if plot else op_plot
            val = SpiceRawParser.find_signal(ds, name, type_hint="v")
            if val is None:
                val = SpiceRawParser.find_signal(ds, name, type_hint="i")
            if val is None:
                raise ValueError(f"OP signal '{name}' not found.")
            return val[0] if len(val) > 0 else None

        def plot_func(x, y=None, label=None, title=None):
            self.viewer.plot(x, y, label=label)

        def bode(target, plot=None, unwrap_phase=False, wrap_to_180=False):
            # Resolve target to complex array
            if isinstance(target, str):
                y = vf(target, plot)
            else:
                y = target

            self.viewer.bode(y, label=str(target))

        def vdc(name, plot=None):
            ds = self.all_plots.get(plot, dc_plot) if plot else dc_plot
            val = SpiceRawParser.find_signal(ds, name, type_hint="v")
            if val is None:
                raise ValueError(f"DC signal '{name}' not found.")
            return np.array(val)

        def v(name, plot=None):
            """Generic voltage fetcher that tries Tran, then DC, then AC, then OP."""
            for plot_key in (
                [plot]
                if plot
                else [
                    "Transient Analysis",
                    "DC transfer characteristic",
                    "AC Analysis",
                    "Operating Point",
                ]
            ):
                ds = self.all_plots.get(plot_key)
                if not ds:
                    continue
                val = SpiceRawParser.find_signal(ds, name, type_hint="v")
                if val is not None:
                    return val[0] if plot_key == "Operating Point" else np.array(val)
            raise ValueError(f"Signal '{name}' not found in any plot.")

        def mean(x, y, t_start=None, t_stop=None):
            if t_start is None:
                t_start = x[0]
            if t_stop is None:
                t_stop = x[-1]
            mask = (x >= t_start) & (x <= t_stop)
            return np.mean(y[mask])

        def rms(x, y, t_start=None, t_stop=None):
            if t_start is None:
                t_start = x[0]
            if t_stop is None:
                t_stop = x[-1]
            mask = (x >= t_start) & (x <= t_stop)
            return np.sqrt(np.mean(np.array(y[mask], dtype=complex) ** 2))

        def p2p(x, y, t_start=None, t_stop=None):
            if t_start is None:
                t_start = x[0]
            if t_stop is None:
                t_stop = x[-1]
            mask = (x >= t_start) & (x <= t_stop)
            return np.max(y[mask]) - np.min(y[mask])

        def value(x, y, at):
            return np.interp(at, x, y)

        def subaxis(nrows, idx):
            return self.viewer.subaxis(nrows, idx)

        def st(name, plot=None):
            """Generic signal fetcher for Transient results."""
            ds = self.all_plots.get(plot, tran_plot) if plot else tran_plot
            val = SpiceRawParser.find_signal(ds, name)
            if val is None:
                raise ValueError(f"Transient signal '{name}' not found.")
            return np.array(val)

        def sf(name, plot=None):
            """Generic signal fetcher for Frequency (AC) results."""
            ds = self.all_plots.get(plot, ac_plot) if plot else ac_plot
            val = SpiceRawParser.find_signal(ds, name)
            if val is None:
                raise ValueError(f"AC signal '{name}' not found.")
            return np.array(val)

        def sop(name, plot=None):
            """Generic signal fetcher for Operating Point results."""
            ds = self.all_plots.get(plot, op_plot) if plot else op_plot
            val = SpiceRawParser.find_signal(ds, name)
            if val is None:
                raise ValueError(f"OP signal '{name}' not found.")
            return val[0] if len(val) > 0 else None

        def sdc(name, plot=None):
            """Generic signal fetcher for DC sweep results."""
            ds = self.all_plots.get(plot, dc_plot) if plot else dc_plot
            val = SpiceRawParser.find_signal(ds, name)
            if val is None:
                raise ValueError(f"DC signal '{name}' not found.")
            return np.array(val)

        def f3db(result_array, plot_name=None):
            """Calculate 3dB frequency.
            result_array: complex array (e.g. from sf('VOUT'))
            plot_name: optional ac plot name
            """
            if f_vec is None or len(f_vec) == 0:
                raise ValueError("No frequency data available.")

            y = np.array(result_array)
            mag_db = 20 * np.log10(np.abs(y))

            # Lowest frequency as DC gain
            dc_gain_db = mag_db[0]
            target_db = dc_gain_db - 3.0

            # Find crossing.
            idx = np.where(mag_db <= target_db)[0]
            if len(idx) == 0:
                return np.nan

            idx = idx[0]
            if idx == 0:
                return f_vec[0]

            # Interpolate between idx-1 and idx
            f1, f2 = f_vec[idx - 1], f_vec[idx]
            db1, db2 = mag_db[idx - 1], mag_db[idx]

            if abs(db2 - db1) < 1e-12:
                return f1

            logf1, logf2 = np.log10(f1), np.log10(f2)
            logf = logf1 + (logf2 - logf1) * (target_db - db1) / (db2 - db1)
            return 10**logf

        scope = {
            "v": v,
            "vt": st,  # Aliased for backward compatibility
            "it": st,
            "vf": sf,
            "ifc": sf,
            "vdc": sdc,
            "op": sop,
            "st": st,
            "sf": sf,
            "sop": sop,
            "sdc": sdc,
            "mean": mean,
            "rms": rms,
            "p2p": p2p,
            "value": value,
            "plot": plot_func,
            "t": t,
            "f": f_vec,
            "mag": np.abs,
            "db": lambda x: 20 * np.log10(np.abs(x)),
            "dB": lambda x: 20 * np.log10(np.abs(x)),
            "ph": lambda x: np.angle(x, deg=True),
            "np": np,
            "plots": self.all_plots,
            "bode": bode,
            "f3db": f3db,
            "subfigure": self.viewer.subaxis,
            "subaxis": subaxis,
        }

        # Add outputs from the outputs_dock if available
        try:
            # Look for outputs_dock in the main window
            main_window = self.parent()
            # If parent is not MainWindow, try to find it
            while main_window and not hasattr(main_window, "outputs_dock"):
                main_window = main_window.parent()

            if main_window and hasattr(main_window, "outputs_dock"):
                outputs_scope = main_window.outputs_dock.get_results_scope()
                # Prioritize calculator functions over outputs by merging them last
                scope = {**outputs_scope, **scope}
        except Exception as e:
            print(f"Note: Could not load output expressions into calculator scope: {e}")

        return scope
