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


class ConnectivityMixin:
    def _update_pin_connectivity(self):
        scene = self.scene()
        wires = [i for i in scene.items() if isinstance(i, Wire)]

        # Collect all pins and their scene positions for overlap check
        pin_positions = []  # List of (item, pin_id, QPointF)
        schematic_items = [
            i
            for i in scene.items()
            if (hasattr(i, "pins") and isinstance(getattr(i, "pins"), dict))
            or (hasattr(i, "pin_items") and isinstance(getattr(i, "pin_items"), dict))
        ]

        for item in schematic_items:
            if hasattr(item, "pins") and isinstance(item.pins, dict):
                for pid, info in item.pins.items():
                    try:
                        pos = item.mapToScene(info["pos"])
                        pin_positions.append((item, pid, pos))
                    except Exception:
                        continue
            elif hasattr(item, "pin_items") and isinstance(item.pin_items, dict):
                for pid, pin_obj in item.pin_items.items():
                    try:
                        r = pin_obj.rect()
                        pos = pin_obj.mapToScene(r.center())
                        pin_positions.append((item, pid, pos))
                    except Exception:
                        continue

        # Update each item's connected status
        for item in schematic_items:
            connected_ids = []

            # Current item's pins
            item_pins = []
            if hasattr(item, "pins") and isinstance(item.pins, dict):
                for pid, info in item.pins.items():
                    item_pins.append((pid, item.mapToScene(info["pos"])))
            elif hasattr(item, "pin_items") and isinstance(item.pin_items, dict):
                for pid, pin_obj in item.pin_items.items():
                    r = pin_obj.rect()
                    item_pins.append((pid, pin_obj.mapToScene(r.center())))

            for pid, pin_pos in item_pins:
                connected = False

                # 1. Check against wires (including segments)
                for w in wires:
                    l = w.line()
                    p1 = w.mapToScene(l.p1())
                    p2 = w.mapToScene(l.p2())
                    if self.distance_point_to_line_segment(pin_pos, QLineF(p1, p2)) < 1:
                        connected = True
                        break

                if not connected:
                    # 2. Check against OTHER pins (overlapping pins)
                    for other_item, other_pid, other_pos in pin_positions:
                        if other_item == item:
                            continue
                        if (pin_pos - other_pos).manhattanLength() < 1:
                            connected = True
                            break

                if connected:
                    connected_ids.append(pid)

            # Apply connectivity update
            if hasattr(item, "set_connected_pins"):
                try:
                    item.set_connected_pins(connected_ids)
                except Exception:
                    pass

    def recalculate_connectivity(self):
        scene = self.scene()
        items = list(scene.items())  # Snapshot

        # 1. Collect and Remove Junctions
        for item in items:
            if isinstance(item, Junction):
                scene.removeItem(item)

        wires = [i for i in scene.items() if isinstance(i, Wire)]
        # Include both SVG-based SchematicItem and programmatic items that expose pins
        schematic_items = [
            i
            for i in scene.items()
            if (hasattr(i, "pins") and isinstance(getattr(i, "pins"), dict))
            or (hasattr(i, "pin_items") and isinstance(getattr(i, "pin_items"), dict))
        ]

        # 1.5 Identify Junction Barriers
        # A barrier is a point that must NOT be merged through because it's a junction (3+ wires or T)
        connection_counts = {}
        for w in wires:
            l = w.line()
            p1 = w.mapToScene(l.p1())
            p2 = w.mapToScene(l.p2())
            for p in [p1, p2]:
                pt = (round(p.x(), 2), round(p.y(), 2))
                connection_counts[pt] = connection_counts.get(pt, 0) + 1

        barriers = set()
        for pt, count in connection_counts.items():
            if count >= 3:
                barriers.add(pt)

        # Add T-junctions to barriers
        for w1 in wires:
            l1 = w1.line()
            p1_start = w1.mapToScene(l1.p1())
            p1_end = w1.mapToScene(l1.p2())
            for p1 in [p1_start, p1_end]:
                pt1 = (round(p1.x(), 2), round(p1.y(), 2))
                if pt1 in barriers:
                    continue
                for w2 in wires:
                    if w1 == w2:
                        continue
                    l2 = w2.line()
                    p2a = w2.mapToScene(l2.p1())
                    p2b = w2.mapToScene(l2.p2())
                    if self.distance_point_to_line_segment(p1, QLineF(p2a, p2b)) < 1:
                        barriers.add(pt1)

        # 2. Wire Merging: Merge collinear overlapping/touching segments
        # Group by orientation and position
        h_groups = {}  # y -> list of wires
        v_groups = {}  # x -> list of wires
        others = []

        for w in wires:
            l = w.line()
            p1 = w.mapToScene(l.p1())
            p2 = w.mapToScene(l.p2())
            if abs(p1.y() - p2.y()) < 0.1:  # Horizontal
                y = round(p1.y(), 2)
                h_groups.setdefault(y, []).append(w)
            elif abs(p1.x() - p2.x()) < 0.1:  # Vertical
                x = round(p1.x(), 2)
                v_groups.setdefault(x, []).append(w)
            else:
                others.append(w)

        def merge_segments(wire_list, is_horizontal, barriers, coord_fixed):
            if not wire_list:
                return []
            # Extract intervals [min, max]
            intervals = []
            for w in wire_list:
                l = w.line()
                p1 = w.mapToScene(l.p1())
                p2 = w.mapToScene(l.p2())
                if is_horizontal:
                    intervals.append((min(p1.x(), p2.x()), max(p1.x(), p2.x()), w))
                else:
                    intervals.append((min(p1.y(), p2.y()), max(p1.y(), p2.y()), w))

            # Sort by start (and end) only. Avoid comparing Wire objects which
            # may be present as the third tuple element and are not orderable.
            intervals.sort(key=lambda t: (t[0], t[1]))

            merged = []
            if not intervals:
                return []

            curr_start, curr_end, curr_wires = (
                intervals[0][0],
                intervals[0][1],
                [intervals[0][2]],
            )

            for i in range(1, len(intervals)):
                start, end, w = intervals[i]

                # Barrier check at curr_end
                pt = (
                    (round(curr_end, 2), coord_fixed)
                    if is_horizontal
                    else (coord_fixed, round(curr_end, 2))
                )
                is_at_barrier = pt in barriers

                if (
                    start <= curr_end + 0.1 and not is_at_barrier
                ):  # Overlap/touch AND no barrier
                    if end > curr_end:
                        curr_end = end
                    curr_wires.append(w)
                else:
                    merged.append((curr_start, curr_end, curr_wires))
                    curr_start, curr_end, curr_wires = start, end, [w]
            merged.append((curr_start, curr_end, curr_wires))
            return merged

        # Execute Merging
        for y, group in h_groups.items():
            merged_data = merge_segments(group, True, barriers, y)
            for start, end, old_wires in merged_data:
                if len(old_wires) > 1:
                    # Create new merged wire
                    new_w = Wire(QPointF(start, y), QPointF(end, y))
                    # Keep name if any
                    names = [w.name for w in old_wires if w.name]
                    if names:
                        new_w.name = names[0]
                    scene.addItem(new_w)
                    # Remove old ones
                    for w in old_wires:
                        if w in scene.items():
                            scene.removeItem(w)

        for x, group in v_groups.items():
            merged_data = merge_segments(group, False, barriers, x)
            for start, end, old_wires in merged_data:
                if len(old_wires) > 1:
                    new_w = Wire(QPointF(x, start), QPointF(x, end))
                    names = [w.name for w in old_wires if w.name]
                    if names:
                        new_w.name = names[0]
                    scene.addItem(new_w)
                    for w in old_wires:
                        if w in scene.items():
                            scene.removeItem(w)

        # Update wires list after merging
        wires = [i for i in scene.items() if isinstance(i, Wire)]

        # 3. Connection Mapping & Junction Placement
        # We need to find points where 3+ wires meet OR T-junctions
        connection_counts = {}  # pos_tuple -> count
        wire_lines = []
        for w in wires:
            l = w.line()
            p1 = w.mapToScene(l.p1())
            p2 = w.mapToScene(l.p2())
            pts = [
                (round(p1.x(), 2), round(p1.y(), 2)),
                (round(p2.x(), 2), round(p2.y(), 2)),
            ]
            wire_lines.append((w, p1, p2, QLineF(p1, p2), pts))
            for pt in pts:
                connection_counts[pt] = connection_counts.get(pt, 0) + 1

        # Junction Locations
        junction_pts = set()

        # Rule A: 3+ wire endpoints meet
        for pt, count in connection_counts.items():
            if count >= 3:
                junction_pts.add(pt)

        # Rule B: T-Junction (endpoint of one wire on segment of another)
        for i, (w1, p1a, p1b, l1, pts1) in enumerate(wire_lines):
            for j, (w2, p2a, p2b, l2, pts2) in enumerate(wire_lines):
                if i == j:
                    continue
                # Check endpoints of w1 against segment w2
                for p in [p1a, p1b]:
                    pt = (round(p.x(), 2), round(p.y(), 2))
                    if pt in pts2:
                        continue  # Already handled by Rule A or it's a corner
                    if self.distance_point_to_line_segment(p, l2) < 1:
                        junction_pts.add(pt)

        # Add Junctions to scene
        for pt in junction_pts:
            scene.addItem(Junction(QPointF(pt[0], pt[1])))

        # 4. Pin Status & Connectivity propagation
        self._update_pin_connectivity()

        # 5. Net Name Propagation
        # Build adjacency graph
        adj = {i: [] for i in range(len(wires))}
        for i in range(len(wires)):
            w1, p1a, p1b, l1, pts1 = wire_lines[i]
            for j in range(i + 1, len(wires)):
                w2, p2a, p2b, l2, pts2 = wire_lines[j]

                connected = False
                # Shared endpoint
                if set(pts1) & set(pts2):
                    connected = True

                # T-junction
                if not connected:
                    if (
                        self.distance_point_to_line_segment(p1a, l2) < 1
                        or self.distance_point_to_line_segment(p1b, l2) < 1
                        or self.distance_point_to_line_segment(p2a, l1) < 1
                        or self.distance_point_to_line_segment(p2b, l1) < 1
                    ):
                        connected = True

                if connected:
                    adj[i].append(j)
                    adj[j].append(i)

        # Traverse and Propagate
        visited = set()
        for i in range(len(wires)):
            if i not in visited:
                stack = [i]
                group = []
                net_names = set()
                while stack:
                    curr = stack.pop()
                    if curr in visited:
                        continue
                    visited.add(curr)
                    group.append(curr)
                    if wires[curr].name:
                        net_names.add(wires[curr].name)
                    for neighbor in adj[curr]:
                        if neighbor not in visited:
                            stack.append(neighbor)

                if net_names:
                    # Pick a consensus name
                    # Priority:
                    # 1. Any 'net_override' from a connected pin (e.g. GND -> '0')
                    # 2. If many overrides, pick one (usually '0' if present)
                    # 3. If any wire in the group is selected, its name wins.
                    # 4. Fallback to sorted list

                    # Find overrides (SVG-based pins may carry a 'net_override')
                    overrides = set()
                    for idx in group:
                        w = wires[idx]
                        l = w.line()
                        p1, p2 = w.mapToScene(l.p1()), w.mapToScene(l.p2())
                        for item in schematic_items:
                            # SVG-based SchematicItem: pins is a dict mapping -> {'pos': QPointF, ...}
                            if hasattr(item, "pins") and isinstance(
                                getattr(item, "pins"), dict
                            ):
                                for pid, info in item.pins.items():
                                    try:
                                        pin_scene = item.mapToScene(info["pos"])
                                    except Exception:
                                        continue
                                    if (pin_scene - p1).manhattanLength() < 1 or (
                                        pin_scene - p2
                                    ).manhattanLength() < 1:
                                        if "net_override" in info:
                                            overrides.add(info["net_override"])
                            # Programmatic pcells: they expose pin_items dict of QGraphicsRectItem.
                            # Those items do not currently carry 'net_override' metadata, so we skip
                            # override detection for them here. If needed, pcells can provide
                            # their own override logic via format_netlist or by attaching metadata
                            # to the pin QGraphicsRectItem.

                    if overrides:
                        # Priority: '0' wins if multiple exist
                        if "0" in overrides:
                            consensus = "0"
                        else:
                            consensus = sorted(list(overrides))[0]
                    else:
                        selected_names = set()
                        for idx in group:
                            if wires[idx].isSelected() and wires[idx].name:
                                selected_names.add(wires[idx].name)

                        if len(selected_names) == 1:
                            consensus = list(selected_names)[0]
                        else:
                            consensus = sorted(list(net_names))[0]

                    for idx in group:
                        wires[idx].name = consensus

        # 6. Evaluate Netlist Nodes for Labels
        try:
            # We silently simulate a netlist generation sequence using the live scene
            # specifically to extract the calculated node map for wire visualization.
            gen = NetlistGenerator(self.scene(), [], [])
            gen.generate()
            for w in wires:
                net = gen.item_node_map.get(w)
                if net:
                    w.net_name = net
                w.update()
        except Exception:
            pass

    def distance_point_to_line_segment(self, point, line):
        p = point
        a = line.p1()
        b = line.p2()

        # Vector ab
        ab = b - a
        ap = p - a

        # Project ap onto ab
        len_sq = ab.x() ** 2 + ab.y() ** 2
        if len_sq == 0:
            return (p - a).manhattanLength()

        t = (ap.x() * ab.x() + ap.y() * ab.y()) / len_sq

        # Clamp t to segment [0, 1]
        t = max(0, min(1, t))

        # Closest point
        closest = a + ab * t
        return (p - closest).manhattanLength()
