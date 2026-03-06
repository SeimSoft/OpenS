import os
import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QToolBar,
    QLabel,
    QSplitter,
    QDockWidget,
    QStatusBar,
    QMenu,
    QTextEdit,
)
from PyQt6.QtGui import QAction, QColor, QIcon
from PyQt6.QtCore import Qt, pyqtSignal, QPointF

# Set some global PyQtGraph configs for better performance
pg.setConfigOption("antialias", False)  # Fast
pg.setConfigOption("background", (20, 20, 20))
pg.setConfigOption("foreground", "d")


class SignalItem:
    def __init__(self, name, x, y, plot_data_item, axis_idx):
        self.name = name
        self.x = x
        self.y = y
        self.plot_data_item = plot_data_item
        self.axis_idx = axis_idx


class WaveformViewer(QMainWindow):
    openCalculatorRequested = pyqtSignal()
    refreshRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Waveform Viewer")
        self.resize(1200, 800)

        # Internal state
        self.plots = []  # List of pg.PlotItem
        self.signals = {}  # {name: SignalItem}
        self.cursors = {}  # {'A': line, 'B': line, 'Probe': line}

        self.last_mouse_scene_pos = None
        self.custom_markers = []
        self.markers_data = {}
        self.selected_signal = None

        self.hover_text = pg.TextItem(
            "", color="black", fill=pg.mkBrush(255, 255, 255, 200)
        )
        self.hover_text.setZValue(100)
        self.hover_text_added_to = None

        self._setup_ui()
        self._setup_toolbar()

    def _setup_ui(self):
        self.central_widget = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(self.central_widget)

        # Graphics Layout
        self.glw = pg.GraphicsLayoutWidget()
        self.glw.ci.setSpacing(0)
        self.central_widget.addWidget(self.glw)

        # Signal Browser Dock
        self.browser_dock = QDockWidget("Signals", self)
        self.signal_tree = QTreeWidget()
        self.signal_tree.setHeaderLabels(["Plot / Signal", "Value"])
        self.signal_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.signal_tree.customContextMenuRequested.connect(self._show_browser_menu)
        self.signal_tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        self.browser_dock.setWidget(self.signal_tree)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.browser_dock)

        # Status Bar for measurements
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready")

        # Measurements Dock
        self.measurements_dock = QDockWidget("Measurements", self)
        self.measurements_text = QTextEdit()
        self.measurements_text.setReadOnly(True)
        # Use Monospace font for alignment
        font = self.measurements_text.font()
        font.setFamily("Courier New")
        self.measurements_text.setFont(font)
        self.measurements_dock.setWidget(self.measurements_text)
        self.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea, self.measurements_dock
        )

        self.glw.scene().sigMouseMoved.connect(self.on_mouse_moved)

    def on_mouse_moved(self, pos):
        self.last_mouse_scene_pos = pos

        view_box = None
        plot_item = None
        for p in self.plots:
            vb = p.getViewBox()
            if vb.sceneBoundingRect().contains(pos):
                view_box = vb
                plot_item = p
                break

        if not view_box:
            if self.hover_text_added_to:
                try:
                    self.hover_text_added_to.removeItem(self.hover_text)
                except Exception:
                    pass
                self.hover_text_added_to = None
            return

        mouse_point = view_box.mapSceneToView(pos)
        mx, my = mouse_point.x(), mouse_point.y()

        min_dist = float("inf")
        best_pt = None
        best_name = None
        rect = view_box.viewRect()
        rx, ry = rect.width(), rect.height()
        if rx == 0 or ry == 0:
            return

        for sig in self.signals.values():
            if len(self.plots) > sig.axis_idx and self.plots[sig.axis_idx] == plot_item:
                dx = (sig.x - mx) / rx
                dy = (sig.y - my) / ry
                dist = dx**2 + dy**2
                idx = np.argmin(dist)
                d = dist[idx]
                if d < 0.005 and d < min_dist:
                    min_dist = d
                    best_pt = (sig.x[idx], sig.y[idx])
                    best_name = sig.name

        if best_pt:
            from opens_suite.design_points import DesignPoints

            x_str = DesignPoints._format_si(best_pt[0])
            y_str = DesignPoints._format_si(best_pt[1])
            self.hover_text.setText(f"{best_name}\nx={x_str}\ny={y_str}")
            self.hover_text.setPos(best_pt[0], best_pt[1])
            if self.hover_text_added_to != plot_item:
                if self.hover_text_added_to:
                    try:
                        self.hover_text_added_to.removeItem(self.hover_text)
                    except Exception:
                        pass
                plot_item.addItem(self.hover_text)
                self.hover_text_added_to = plot_item
        else:
            if self.hover_text_added_to:
                try:
                    self.hover_text_added_to.removeItem(self.hover_text)
                except Exception:
                    pass
                self.hover_text_added_to = None

    def keyPressEvent(self, event):
        key = event.text().upper()
        if key == "F":
            for p in self.plots:
                p.autoRange()
        elif key == "R":
            self.refreshRequested.emit()
        elif key in ["A", "B", "V", "H", "E"]:
            self.handle_cursor_key(key)
        else:
            super().keyPressEvent(event)

    def handle_cursor_key(self, key):
        if key == "E":
            for item in self.custom_markers:
                for p in self.plots:
                    try:
                        p.removeItem(item)
                    except:
                        pass
            self.custom_markers.clear()
            self.markers_data.clear()
            self._update_measurements()
            return

        if not self.last_mouse_scene_pos:
            return
        pos = self.last_mouse_scene_pos

        view_box = None
        plot_item = None
        for p in self.plots:
            vb = p.getViewBox()
            if vb.sceneBoundingRect().contains(pos):
                view_box = vb
                plot_item = p
                break

        if not view_box:
            return

        mouse_point = view_box.mapSceneToView(pos)
        mx, my = mouse_point.x(), mouse_point.y()

        if key in ["A", "B"]:
            min_dist = float("inf")
            best_pt = None
            rect = view_box.viewRect()
            rx, ry = rect.width(), rect.height()
            if rx == 0 or ry == 0:
                return

            for sig in self.signals.values():
                if self.plots[sig.axis_idx] == plot_item:
                    dx = (sig.x - mx) / rx
                    dy = (sig.y - my) / ry
                    dist = dx**2 + dy**2
                    idx = np.argmin(dist)
                    d = dist[idx]
                    if d < min_dist:
                        min_dist = d
                        best_pt = (sig.x[idx], sig.y[idx])

            if best_pt:
                old_item = self.markers_data.get(f"{key}_item")
                if old_item:
                    for p in self.plots:
                        try:
                            p.removeItem(old_item)
                        except:
                            pass
                    if old_item in self.custom_markers:
                        self.custom_markers.remove(old_item)
                old_text = self.markers_data.get(f"{key}_text")
                if old_text:
                    for p in self.plots:
                        try:
                            p.removeItem(old_text)
                        except:
                            pass
                    if old_text in self.custom_markers:
                        self.custom_markers.remove(old_text)

                color = "cyan" if key == "A" else "yellow"
                scatter = pg.ScatterPlotItem(
                    size=10, pen=pg.mkPen(None), brush=pg.mkBrush(color)
                )
                scatter.addPoints([{"pos": best_pt}])
                plot_item.addItem(scatter)
                self.custom_markers.append(scatter)

                text = pg.TextItem(f"{key}", color=color, anchor=(0, 1))
                text.setPos(*best_pt)
                plot_item.addItem(text)
                self.custom_markers.append(text)

                self.markers_data[f"{key}_item"] = scatter
                self.markers_data[f"{key}_text"] = text
                self.markers_data[key] = best_pt

                self._update_measurements()

        elif key == "V":
            line = pg.InfiniteLine(
                angle=90,
                movable=False,
                pos=mx,
                pen=pg.mkPen("red", width=1, style=Qt.PenStyle.DashLine),
            )
            plot_item.addItem(line)
            self.custom_markers.append(line)

            vals = []
            for sig in self.signals.values():
                try:
                    sort_idx = np.argsort(sig.x)
                    sx = sig.x[sort_idx]
                    sy = sig.y[sort_idx]
                    if sx[0] <= mx <= sx[-1]:
                        y_val = np.interp(mx, sx, sy)
                        vals.append(f"{sig.name}: y={y_val:.4g}")
                except:
                    pass

            text = "V-Line @ x={:.4g}\n".format(mx) + "\n".join(vals)
            self.markers_data[f"V_{mx}_{len(self.custom_markers)}"] = text
            self._update_measurements()

        elif key == "H":
            line = pg.InfiniteLine(
                angle=0,
                movable=False,
                pos=my,
                pen=pg.mkPen("green", width=1, style=Qt.PenStyle.DashLine),
            )
            plot_item.addItem(line)
            self.custom_markers.append(line)

            vals = []
            for sig in self.signals.values():
                if self.plots[sig.axis_idx] == plot_item:
                    try:
                        sy = sig.y - my
                        crossings = np.where(np.diff(np.sign(sy)))[0]
                        if len(crossings) > 0:
                            xs = []
                            for c in crossings[:5]:
                                if sy[c] == sy[c + 1]:
                                    x_val = sig.x[c]
                                else:
                                    x_val = sig.x[c] - sy[c] * (
                                        sig.x[c + 1] - sig.x[c]
                                    ) / (sy[c + 1] - sy[c])
                                xs.append(f"{x_val:.4g}")
                            res = f"{sig.name}: x=" + ", ".join(xs)
                            if len(crossings) > 5:
                                res += " ..."
                            vals.append(res)
                    except:
                        pass

            text = "H-Line @ y={:.4g}\n".format(my) + "\n".join(vals)
            self.markers_data[f"H_{my}_{len(self.custom_markers)}"] = text
            self._update_measurements()

    def _update_measurements(self):
        lines = []
        if "A" in self.markers_data:
            ax, ay = self.markers_data["A"]
            lines.append(f"A: x={ax:.4g}, y={ay:.4g}")
        if "B" in self.markers_data:
            bx, by = self.markers_data["B"]
            lines.append(f"B: x={bx:.4g}, y={by:.4g}")
        if "A" in self.markers_data and "B" in self.markers_data:
            ax, ay = self.markers_data["A"]
            bx, by = self.markers_data["B"]
            dx = bx - ax
            dy = by - ay
            lines.append(f"Delta (B-A): dx={dx:.4g}, dy={dy:.4g}")

        for k, v in self.markers_data.items():
            if k.startswith("V_") or k.startswith("H_"):
                lines.append("-" * 20)
                lines.append(v)

        self.measurements_text.setPlainText("\n".join(lines))

    def _setup_toolbar(self):
        toolbar = self.addToolBar("Cursor Tools")

        # Calculator
        calc_icon = QIcon(
            os.path.join(os.path.dirname(__file__), "assets", "icons", "calculator.svg")
        )
        self.calc_action = QAction(calc_icon, "Calculator", self)
        self.calc_action.triggered.connect(self.openCalculatorRequested.emit)
        toolbar.addAction(self.calc_action)

        toolbar.addSeparator()

        # Rect Zoom Mode (standard)
        self.rect_zoom_action = QAction("Rect Zoom", self)
        self.rect_zoom_action.setCheckable(True)
        self.rect_zoom_action.setChecked(
            False
        )  # Default to False -> PanMode (right click scale/zoom, left click pan/click)
        self.rect_zoom_action.triggered.connect(self._toggle_rect_zoom)
        toolbar.addAction(self.rect_zoom_action)

        toolbar.addSeparator()

        self.cursor_a_action = QAction("Cursor A", self)
        self.cursor_a_action.setCheckable(True)
        self.cursor_a_action.triggered.connect(lambda: self.toggle_cursor("A"))
        toolbar.addAction(self.cursor_a_action)

        self.cursor_b_action = QAction("Cursor B", self)
        self.cursor_b_action.setCheckable(True)
        self.cursor_b_action.triggered.connect(lambda: self.toggle_cursor("B"))
        toolbar.addAction(self.cursor_b_action)

        toolbar.addSeparator()

        self.probe_cursor_action = QAction("Probe Cursor", self)
        self.probe_cursor_action.setCheckable(True)
        self.probe_cursor_action.triggered.connect(lambda: self.toggle_cursor("Probe"))
        toolbar.addAction(self.probe_cursor_action)

    def _toggle_rect_zoom(self, checked):
        mode = pg.ViewBox.RectMode if checked else pg.ViewBox.PanMode
        for p in self.plots:
            p.getViewBox().setMouseMode(mode)

    def _get_or_create_axis(self, idx):
        while len(self.plots) <= idx:
            # Create new plot
            p = self.glw.addPlot(row=len(self.plots), col=0)
            p.showGrid(x=True, y=True, alpha=0.3)
            p.getViewBox().setMouseMode(
                pg.ViewBox.RectMode
                if self.rect_zoom_action.isChecked()
                else pg.ViewBox.PanMode
            )

            # Sync X axis
            if len(self.plots) > 0:
                p.setXLink(self.plots[0])

            self.plots.append(p)
            self._update_tree()
        return self.plots[idx]

    def add_signal(self, name, x, y, axis_idx=0, color=None):
        if color is None:
            # Simple color rotation
            colors = ["y", "g", "c", "m", "r", "w"]
            color = colors[len(self.signals) % len(colors)]

        plot = self._get_or_create_axis(axis_idx)

        # High performance PlotDataItem
        item = pg.PlotDataItem(
            x,
            y,
            pen=pg.mkPen(color, width=1.5),
            name=name,
        )

        # Make the curve selectable via left-click!
        item.curve.setClickable(True)
        # Mouse event is emitted from PlotCurveItem (item.curve)
        item.curve.sigClicked.connect(
            lambda c, evt, n=name: self._on_curve_clicked(n, c, evt)
        )

        plot.addItem(item)

        self.signals[name] = SignalItem(name, x, y, item, axis_idx)
        self._update_tree()

    def remove_signal(self, name):
        if name in self.signals:
            sig = self.signals.pop(name)
            self.plots[sig.axis_idx].removeItem(sig.plot_data_item)
            self._update_tree()

    def move_signal(self, name, target_idx):
        if name in self.signals:
            sig = self.signals[name]
            if sig.axis_idx == target_idx:
                return

            # Remove from old
            self.plots[sig.axis_idx].removeItem(sig.plot_data_item)

            # Add to new
            target_plot = self._get_or_create_axis(target_idx)
            target_plot.addItem(sig.plot_data_item)
            sig.axis_idx = target_idx
            self._update_tree()

    def _highlight_signal(self, name):
        """Highlight a signal by making it bold and bringing it to top."""
        self.selected_signal = name
        for sig_name, sig in self.signals.items():
            # In pyqtgraph, pen is stored in opts['pen']
            old_pen = sig.plot_data_item.opts.get("pen")

            if sig_name == name:
                width = 4
                sig.plot_data_item.setZValue(10)
            else:
                width = 1.5
                sig.plot_data_item.setZValue(0)

            # Create a new pen with the same color but different width
            new_pen = pg.mkPen(old_pen)
            new_pen.setWidthF(width)
            sig.plot_data_item.setPen(new_pen)

    def _on_tree_selection_changed(self):
        selected_items = self.signal_tree.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        # Check if it's a signal item (has a parent)
        if item.parent():
            sig_name = item.text(0)
            self._highlight_signal(sig_name)

    def _on_curve_clicked(self, name, curve_item, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return

        # Select in tree
        match = self.signal_tree.findItems(
            name, Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive
        )
        if match:
            # Block signals to avoid recursion if we want, but here it's fine
            self.signal_tree.setCurrentItem(match[0])

        self._highlight_signal(name)
        event.accept()

    def _show_browser_menu(self, pos):
        item = self.signal_tree.itemAt(pos)
        if not item:
            return

        menu = QMenu()
        # Check if it's a signal item (has a parent)
        if item.parent():
            sig_name = item.text(0)

            del_action = menu.addAction(f"Delete '{sig_name}'")
            move_menu = menu.addMenu("Move to Axis")
            for i in range(len(self.plots)):
                move_menu.addAction(f"Plot {i+1}")
            move_menu.addAction("New Plot")

            action = menu.exec(self.signal_tree.viewport().mapToGlobal(pos))
            if action == del_action:
                self.remove_signal(sig_name)
            elif action and action.parent() == move_menu:
                if action.text() == "New Plot":
                    self.move_signal(sig_name, len(self.plots))
                else:
                    target = int(action.text().split()[-1]) - 1
                    self.move_signal(sig_name, target)
        else:
            # Plot item? Maybe allow deleting the whole plot?
            plot_idx = self.signal_tree.indexOfTopLevelItem(item)
            del_plot_action = menu.addAction(f"Remove Plot {plot_idx+1}")
            action = menu.exec(self.signal_tree.viewport().mapToGlobal(pos))
            if action == del_plot_action:
                self.remove_plot(plot_idx)

    def remove_plot(self, idx):
        if 0 <= idx < len(self.plots):
            p = self.plots.pop(idx)
            # Remove all signals in this plot from self.signals
            to_remove = [
                name for name, sig in self.signals.items() if sig.axis_idx == idx
            ]
            for r in to_remove:
                del self.signals[r]

            # Reparent or shift indices of other signals?
            # For simplicity, just remove it from layout
            self.glw.removeItem(p)

            # Shift indices
            for sig in self.signals.values():
                if sig.axis_idx > idx:
                    sig.axis_idx -= 1

            self._update_tree()

    def _update_tree(self):
        self.signal_tree.clear()
        for i, plot in enumerate(self.plots):
            plot_item = QTreeWidgetItem([f"Plot {i+1}"])
            self.signal_tree.addTopLevelItem(plot_item)
            for sig_name, sig in self.signals.items():
                if sig.axis_idx == i:
                    sig_node = QTreeWidgetItem([sig_name, ""])
                    plot_item.addChild(sig_node)
        self.signal_tree.expandAll()

    def toggle_cursor(self, label):
        if label in self.cursors:
            # Remove
            line = self.cursors.pop(label)
            for p in self.plots:
                p.removeItem(line)
            self._update_cursor_readouts()
            return

        # Add
        line = pg.InfiniteLine(
            angle=90,
            movable=True,
            pen=pg.mkPen(
                (
                    QColor("cyan")
                    if label == "A"
                    else QColor("yellow") if label == "B" else QColor("white")
                ),
                width=1,
                style=Qt.PenStyle.DashLine,
            ),
        )
        self.cursors[label] = line

        # Add to all plots (they will be synced)
        for p in self.plots:
            p.addItem(line)

        line.sigPositionChanged.connect(self._update_cursor_readouts)
        self._update_cursor_readouts()

    def _update_cursor_readouts(self):
        msg = []
        if "A" in self.cursors:
            x_a = self.cursors["A"].value()
            msg.append(f"A: {x_a:.4g}")
        if "B" in self.cursors:
            x_b = self.cursors["B"].value()
            msg.append(f"B: {x_b:.4g}")
        if "A" in self.cursors and "B" in self.cursors:
            dx = abs(self.cursors["B"].value() - self.cursors["A"].value())
            msg.append(f"dX: {dx:.4g}")

        self.status.showMessage(" | ".join(msg) if msg else "Ready")

        # Update values in the tree for Probe or active cursors
        # We can also implement a more efficient readout here
        pass

    def clear(self):
        self.glw.clear()
        self.plots = []
        self.signals = {}
        self.cursors = {}
        self.signal_tree.clear()

    # API for Calculator Dialog compatibility
    def subaxis(self, nrows, idx):
        # idx is 1-based usually in matplotlib
        return self._get_or_create_axis(idx - 1)

    def plot(self, x, y=None, label=None, **kwargs):
        if y is None:
            y = x
            x = np.arange(len(y))

        if np.iscomplexobj(y):
            y = np.abs(y)

        # Use latest axis by default or first
        axis_idx = len(self.plots) - 1 if self.plots else 0
        self.add_signal(label or f"Signal {len(self.signals)}", x, y, axis_idx=axis_idx)

    def bode(self, complex_y, label=None):
        """Magnitude/Phase plots for AC results."""
        # Try to find frequency vector from existing signals
        f = None
        for sig in self.signals.values():
            if sig.name.lower() in ["f", "frequency"]:
                f = sig.x
                break

        if f is None:
            # Fallback logspace
            f = np.logspace(0, 9, len(complex_y))

        mag_db = 20 * np.log10(np.abs(complex_y))
        ph_deg = np.angle(complex_y, deg=True)

        idx_mag = len(self.plots)
        self.subaxis(2, idx_mag + 1)
        self.add_signal(f"{label} (Mag)", f, mag_db, axis_idx=idx_mag)
        self.plots[idx_mag].setLogMode(x=True, y=False)
        self.plots[idx_mag].setLabel("left", "Magnitude", "dB")

        idx_ph = len(self.plots)
        self.subaxis(2, idx_ph + 1)
        self.add_signal(f"{label} (Phase)", f, ph_deg, axis_idx=idx_ph)
        self.plots[idx_ph].setLogMode(x=True, y=False)
        self.plots[idx_ph].setLabel("left", "Phase", "deg")
        self.plots[idx_ph].setLabel("bottom", "Frequency", "Hz")
        self.plots[idx_ph].setXLink(self.plots[idx_mag])
