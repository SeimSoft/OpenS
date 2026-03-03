from PyQt6.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
)
from PyQt6.QtCore import (
    Qt,
    QPointF,
    QRectF,
    QLineF,
    QProcess,
    QMimeData,
    pyqtSignal,
    QThread,
    QSettings,
)
import math
from PyQt6.QtGui import (
    QPainter,
    QPen,
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QKeyEvent,
    QMouseEvent,
    QCursor,
    QUndoStack,
    QPainterPath,
    QTransform,
)

from opens_suite.schematic_item import SchematicItem
from opens_suite.wire import Wire, Junction
from opens_suite.commands import (
    InsertItemsCommand,
    RemoveItemsCommand,
    MoveItemsCommand,
    CreateWireCommand,
    TransformItemsCommand,
)
import xml.etree.ElementTree as ET
import os
from opens_suite.netlister import NetlistGenerator
from opens_suite.spice_parser import SpiceRawParser


class SimulationMixin:
    def load_simulation_results(self, raw_path):
        if not os.path.exists(raw_path):
            return

        self.statusMessage.emit("Loading simulation results...")

        # Collect data for background connectivity check (fast GUI-thread operation)
        scene = self.scene()
        wires_data = []
        for w in [i for i in scene.items() if isinstance(i, Wire)]:
            l = w.line()
            p1 = w.mapToScene(l.p1())
            p2 = w.mapToScene(l.p2())
            # Pack item itself for keying, plus data for geometry/naming
            wires_data.append(
                {"item": w, "p1": p1, "p2": p2, "line": QLineF(p1, p2), "name": w.name}
            )

        items_data = []
        schematic_items = [
            i
            for i in scene.items()
            if (hasattr(i, "pins") and isinstance(getattr(i, "pins"), dict))
            or (hasattr(i, "pin_items") and isinstance(getattr(i, "pin_items"), dict))
        ]
        for item in schematic_items:
            pins = []
            if hasattr(item, "pins") and isinstance(item.pins, dict):
                for pid, info in item.pins.items():
                    try:
                        pins.append((pid, item.mapToScene(info["pos"])))
                    except Exception:
                        continue
            elif hasattr(item, "pin_items") and isinstance(item.pin_items, dict):
                for pid, pin_obj in item.pin_items.items():
                    try:
                        r = pin_obj.rect()
                        pins.append((pid, pin_obj.mapToScene(r.center())))
                    except Exception:
                        continue

            items_data.append(
                {
                    "item": item,
                    "name": item.name,
                    "prefix": item.prefix,
                    "pins": pins,
                }
            )

        self._loader_thread = SimulationResultLoader(
            raw_path, wires_data, items_data, self.analyses
        )
        self._loader_thread.finished.connect(self._on_simulation_results_ready)
        self._loader_thread.error.connect(
            lambda e: self.statusMessage.emit(f"Error loading results: {e}")
        )
        self._loader_thread.start()

    def _on_simulation_results_ready(self, op_results, item_node_map):
        if not op_results:
            self.statusMessage.emit("No simulation results found.")
            return

        self.last_item_to_node = item_node_map

        # Apply to wires and items in UI thread (fast enough once calculations are done)
        from opens_suite.spice_parser import SpiceRawParser

        for item in self.scene().items():
            if isinstance(item, Wire):
                node_name = self.last_item_to_node.get(item)
                if node_name:
                    # Use smart helper to find voltage for this node
                    val = SpiceRawParser.find_signal(
                        op_results, node_name, type_hint="v"
                    )
                    item.voltage = val
                else:
                    item.voltage = None
            elif isinstance(item, SchematicItem):
                item.simulation_results = op_results
                item._update_labels()

        self.scene().update()
        self.statusMessage.emit("Simulation results loaded.")
        self.simulationFinished.emit()


class SimulationResultLoader(QThread):
    finished = pyqtSignal(dict, dict)
    error = pyqtSignal(str)

    def __init__(self, raw_path, wires_data, items_data, analyses):
        super().__init__()
        self.raw_path = raw_path
        self.wires_data = wires_data
        self.items_data = items_data
        self.analyses = analyses

    def run(self):
        try:
            # 1. Parse results (slow part)
            parser = SpiceRawParser(self.raw_path)
            raw_data = parser.parse()
            if not raw_data:
                self.finished.emit({}, {})
                return

            op_results = parser.get_op_results()
            if not op_results:
                self.finished.emit({}, {})
                return

            # 2. Connectivity analysis (computationally heavy)
            item_node_map = self._compute_connectivity()

            self.finished.emit(op_results, item_node_map)
        except Exception as e:
            import traceback

            traceback.print_exc()
            self.error.emit(str(e))

    def _compute_connectivity(self):
        # Implementation of netlist-style connectivity without scene access
        adj = {}
        all_pins = []

        for item_info in self.items_data:
            item = item_info["item"]
            for pid, pos in item_info["pins"]:
                pin_ref = (item, pid)
                all_pins.append((pin_ref, pos))
                adj[pin_ref] = []

        for w_info in self.wires_data:
            w = w_info["item"]
            adj[w] = []

        # Edges
        def distance_p_to_l(p, l):
            ap = p - l.p1()
            ab = l.p2() - l.p1()
            len_sq = ab.x() ** 2 + ab.y() ** 2
            if len_sq == 0:
                return (p - l.p1()).manhattanLength()
            t = max(0, min(1, (ap.x() * ab.x() + ap.y() * ab.y()) / len_sq))
            proj = l.p1() + t * ab
            return (p - proj).manhattanLength()

        for w_info in self.wires_data:
            w = w_info["item"]
            p1, p2, sl = w_info["p1"], w_info["p2"], w_info["line"]
            for w2_info in self.wires_data:
                w2 = w2_info["item"]
                p2a, p2b, sl2 = w2_info["p1"], w2_info["p2"], w2_info["line"]
                if w == w2:
                    continue
                if (
                    distance_p_to_l(p1, sl2) < 1
                    or distance_p_to_l(p2, sl2) < 1
                    or distance_p_to_l(p2a, sl) < 1
                    or distance_p_to_l(p2b, sl) < 1
                ):
                    adj[w].append(w2)
                    adj[w2].append(w)

            for pin_ref, pos in all_pins:
                if distance_p_to_l(pos, sl) < 1:
                    adj[w].append(pin_ref)
                    adj[pin_ref].append(w)

        # Traverse
        visited = set()
        node_counter = 1
        item_node_map = {}

        def get_group_name(group_items):
            for item in group_items:
                if isinstance(item, tuple):
                    sch_item, pin_id = item
                    item_prefix = ""
                    for info in self.items_data:
                        if info["item"] == sch_item:
                            item_prefix = info["prefix"]
                            break
                    if item_prefix == "GND":
                        return "0"

            for item in group_items:
                if not isinstance(item, tuple):
                    # For wires, check user-assigned names
                    for info in self.wires_data:
                        if info["item"] == item and info["name"]:
                            return info["name"]
            return None

        all_nodes = list(adj.keys())
        for start_node in all_nodes:
            if start_node in visited:
                continue
            group = []
            stack = [start_node]
            visited.add(start_node)
            while stack:
                curr = stack.pop()
                group.append(curr)
                for n in adj.get(curr, []):
                    if n not in visited:
                        visited.add(n)
                        stack.append(n)

            name = get_group_name(group) or f"N_{node_counter}"
            if not get_group_name(group):
                node_counter += 1

            for item in group:
                item_node_map[item] = name

        return item_node_map
