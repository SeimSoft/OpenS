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
    QEvent,
)
import math
import random
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
from opens_suite.theme import theme_manager

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


class EventsMixin:
    def wheelEvent(self, event):
        modifiers = event.modifiers()
        if modifiers & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        ):
            if event.angleDelta().y() > 0:
                factor = self.zoom_factor
            else:
                factor = 1 / self.zoom_factor

            # Use Qt built-in anchor for perfect alignment under mouse
            old_anchor = self.transformationAnchor()
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
            self.scale(factor, factor)
            self.setTransformationAnchor(old_anchor)
            event.accept()
        else:
            super().wheelEvent(event)

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.NativeGesture:
            if event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
                factor = 1.0 + event.value()
                # Use current viewport anchor logic for gesture center
                old_anchor = self.transformationAnchor()
                self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
                self.scale(factor, factor)
                self.setTransformationAnchor(old_anchor)
                return True
        return super().viewportEvent(event)

    def _delete_selected(self):
        items = self.scene().selectedItems()
        if items:
            cmd = RemoveItemsCommand(self.scene(), items)
            self.undo_stack.push(cmd)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Delete or event.key() == Qt.Key.Key_Backspace:
            self._delete_selected()
        elif event.key() == Qt.Key.Key_Escape:
            if self.current_mode == self.MODE_WIRE and self.current_wire:
                self.scene().removeItem(self.current_wire)
                self.current_wire = None
                self.wire_start = None

            self.set_mode(self.MODE_SELECT)

        elif (
            event.key() == Qt.Key.Key_W
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            self.set_mode(self.MODE_WIRE)
        elif (
            event.key() == Qt.Key.Key_M
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            self.set_mode(self.MODE_MOVE)
        elif (
            event.key() == Qt.Key.Key_C
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            self.set_mode(self.MODE_COPY)
        elif (
            event.key() == Qt.Key.Key_L
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            self.set_mode(self.MODE_LINE)
        elif (
            event.key() == Qt.Key.Key_R
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            # Rotation around selection center
            items = [
                it for it in self.scene().selectedItems() if it.parentItem() is None
            ]
            if items:
                self._transform_selection(mode="rotate")

        elif event.key() == Qt.Key.Key_Z and (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.undo_stack.redo()
            else:
                self.undo_stack.undo()

        elif event.key() == Qt.Key.Key_Space:
            items = self.scene().selectedItems()
            probed_names = []

            for item in items:
                if isinstance(item, Wire):
                    if (
                        hasattr(self, "last_item_to_node")
                        and self.last_item_to_node
                        and item in self.last_item_to_node
                    ):
                        raw_name = self.last_item_to_node[item]
                    else:
                        raw_name = item.name or item.net_name or "N_?"

                    canon = self._canonical_probe_net_name(raw_name)
                    if canon is None and (item.name or item.net_name):
                        canon = self._canonical_probe_net_name(item.name or item.net_name)
                    if canon:
                        probed_names.append(canon)
                elif isinstance(item, SchematicItem):
                    if item.name:
                        probed_names.append(item.name + "#branch")

            if not probed_names:
                return

            if len(probed_names) == 2 and all(isinstance(i, Wire) for i in items[:2]):
                n1, n2 = probed_names[0], probed_names[1]
                self.netProbed.emit(f"DIFF:{n1},{n2}")
            else:
                for name in probed_names:
                    self.netProbed.emit(name)

        elif event.key() == Qt.Key.Key_9 and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self._highlight_selected_net()
        elif event.key() == Qt.Key.Key_0 and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self._unhighlight_all_nets()
        elif event.key() == Qt.Key.Key_F:
            self.fitInView(
                self.scene().itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio
            )
        elif event.key() == Qt.Key.Key_E:
            if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                if hasattr(self, "hierarchy_prefix") and self.hierarchy_prefix:
                    self.returnToParentRequested.emit()
            elif event.modifiers() == Qt.KeyboardModifier.NoModifier:
                # Mirror selection horizontally across selection center
                items = [
                    it for it in self.scene().selectedItems() if it.parentItem() is None
                ]
            if items:
                self._transform_selection(mode="mirror")
        else:
            # Check for symbol bindkeys: require Shift + <letter> to avoid collisions
            modifiers = event.modifiers()
            # On some systems (esp. macOS), Shift+[KEY] can include other bits like KeypadModifier.
            # We want to check if Shift is pressed AND no major modifiers (Ctrl, Alt, Meta) are pressed.
            major_modifiers = (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.AltModifier
                | Qt.KeyboardModifier.MetaModifier
            )
            is_allowed_modifier = (
                modifiers == Qt.KeyboardModifier.NoModifier
                or modifiers == Qt.KeyboardModifier.ShiftModifier
            )

            # Use key() for more robust matching, especially on macOS
            key_code = event.key()
            is_alpha = Qt.Key.Key_A <= key_code <= Qt.Key.Key_Z

            if is_allowed_modifier and is_alpha:
                key = chr(key_code).lower()

                # Get library from main window - more robust traversal
                main_window = self.window()
                from opens_suite.main_window import MainWindow

                # If current window isn't MainWindow, try to find it
                if not isinstance(main_window, MainWindow):
                    parent = self.parent()
                    found = False
                    while parent:
                        if isinstance(parent, MainWindow):
                            main_window = parent
                            found = True
                            break
                        parent = parent.parent()

                    if not found:
                        # Final fallback: search all top level widgets
                        from PyQt6.QtWidgets import QApplication

                        for widget in QApplication.topLevelWidgets():
                            if isinstance(widget, MainWindow):
                                main_window = widget
                                found = True
                                break

                if hasattr(main_window, "library_dock"):
                    symbol_path = main_window.library_dock.get_symbol_by_bindkey(key)
                    if symbol_path:
                        # Place symbol at current cursor position (snapped to grid)
                        vp_pos = self.mapFromGlobal(QCursor.pos())
                        cursor_pos = self.mapToScene(vp_pos)
                        cursor_pos = self.snap_to_grid(cursor_pos)
                        item = SchematicItem(symbol_path)
                        item.setPos(cursor_pos)

                        self._assign_name(item)

                        from opens_suite.commands import InsertItemsCommand

                        cmd = InsertItemsCommand(self.scene(), [item])
                        self.undo_stack.push(cmd)

                        import os

                        self.statusMessage.emit(
                            f"Added {os.path.basename(symbol_path).replace('.svg', '')} with key 'Shift+{key.upper()}'"
                        )
                        event.accept()
                        return

            super().keyPressEvent(event)

    def snap_to_grid(self, pos: QPointF):
        grid_size = 10  # Half of visual grid? Or full? Let's say 10
        x = round(pos.x() / grid_size) * grid_size
        y = round(pos.y() / grid_size) * grid_size
        return QPointF(x, y)

    def _get_wire_net_name(self, wire):
        """Return the net name for a wire, using last_item_to_node if available."""
        fallback_name = wire.name or wire.net_name
        if (
            hasattr(self, "last_item_to_node")
            and self.last_item_to_node
            and wire in self.last_item_to_node
        ):
            mapped = self.last_item_to_node[wire]
            # Some connectivity paths can yield instance-pin pseudo names
            # (e.g. X_3:P2). Prefer explicit wire names when available.
            if self._looks_like_instance_pin_name(mapped) and fallback_name:
                return fallback_name
            return mapped
        return fallback_name

    @staticmethod
    def _looks_like_instance_pin_name(name):
        if not name or ":" not in str(name):
            return False
        lhs, rhs = str(name).split(":", 1)
        if not lhs or not rhs:
            return False
        # Heuristic: instance-like left side and pin-like right side.
        return lhs[0].upper() == "X" and rhs[0].upper() == "P"

    def _bridge_to_parent_full_net(self, name):
        if not name:
            return None
        pin_map = getattr(self, "_child_pin_parent_nets", {}) or {}
        s = str(name)
        if s in pin_map:
            return pin_map[s]
        if ":" in s:
            pin_id = s.split(":")[-1]
            if pin_id in pin_map:
                return pin_map[pin_id]
        return None

    def _canonical_probe_net_name(self, name):
        bridged = self._bridge_to_parent_full_net(name)
        if bridged:
            return bridged
        if self._looks_like_instance_pin_name(name):
            # Ignore pseudo instance-pin names like X_3:P2.
            return None
        return self._full_net_name(name)

    def _full_net_name(self, net_name):
        if not net_name:
            return None
        net_name = str(net_name)
        if ":" in net_name:
            return net_name
        return f"{getattr(self, 'hierarchy_prefix', '')}{net_name}"

    def _get_pin_item_net_name(self, item):
        if not isinstance(item, SchematicItem):
            return None
        is_pin_like = (
            item.category in ("IO", "Global")
            or item.prefix == "PIN"
            or getattr(item, "is_global_net", False)
        )
        if not is_pin_like:
            return None
        params = getattr(item, "parameters", {}) or {}
        return params.get("NET_NAME") or item.name

    def _get_highlight_store(self):
        main_window = self.window()
        if not hasattr(main_window, "_net_highlight_full_names"):
            main_window._net_highlight_full_names = set()
        if not hasattr(main_window, "_net_highlight_colors"):
            main_window._net_highlight_colors = {}
        return main_window._net_highlight_full_names, main_window._net_highlight_colors

    def apply_net_highlight_full_names(self, full_names=None):
        if full_names is None:
            full_names, color_map = self._get_highlight_store()
            full_names = set(full_names)
        else:
            full_names = set(full_names)
            _, color_map = self._get_highlight_store()

        # If child-highlight pin IDs were propagated, convert them to mapped local nets.
        pin_ids = set(getattr(self, "_highlight_pin_ids", set()))
        if pin_ids and hasattr(self, "last_item_to_node") and self.last_item_to_node:
            for key, mapped_name in self.last_item_to_node.items():
                if not isinstance(key, tuple) or len(key) != 2:
                    continue
                _, pin_id = key
                if str(pin_id) in pin_ids and mapped_name:
                    mapped_full = self._canonical_probe_net_name(mapped_name)
                    if mapped_full:
                        full_names.add(mapped_full)

        for item in self.scene().items():
            if isinstance(item, Wire):
                local_name = self._get_wire_net_name(item)
                full_name = self._canonical_probe_net_name(local_name)
                item.highlight_color = color_map.get(full_name)
                item.update()
            elif isinstance(item, SchematicItem):
                local_pin_name = self._get_pin_item_net_name(item)
                full_name = self._canonical_probe_net_name(local_pin_name)
                item_color = color_map.get(full_name)

                # Fallback: if this item has highlighted pin IDs, derive color via connectivity map.
                if (
                    item_color is None
                    and pin_ids
                    and hasattr(item, "pins")
                    and hasattr(self, "last_item_to_node")
                ):
                    for pin_id in item.pins.keys():
                        if str(pin_id) not in pin_ids:
                            continue
                        mapped_name = self.last_item_to_node.get((item, pin_id))
                        mapped_full = self._canonical_probe_net_name(mapped_name or pin_id)
                        item_color = color_map.get(mapped_full)
                        if item_color is not None:
                            break

                item.net_highlight_color = item_color
                item.update()

        # Geometric fallback for child pin IDs when connectivity map does not
        # yet resolve to local nets (e.g. freshly opened child without sim map).
        if pin_ids:
            self._apply_pin_component_highlights(pin_ids, color_map)

    def _wire_endpoints_scene(self, wire):
        line = wire.line()
        return wire.mapToScene(line.p1()), wire.mapToScene(line.p2())

    def _wire_touches_pos(self, wire, pos, tol=2.5):
        p1, p2 = self._wire_endpoints_scene(wire)
        return self._distance_point_to_line(pos, p1, p2) <= tol

    def _wires_connected(self, w1, w2):
        a1, a2 = self._wire_endpoints_scene(w1)
        b1, b2 = self._wire_endpoints_scene(w2)
        if (
            (a1 - b1).manhattanLength() < 1
            or (a1 - b2).manhattanLength() < 1
            or (a2 - b1).manhattanLength() < 1
            or (a2 - b2).manhattanLength() < 1
        ):
            return True
        return (
            self._distance_point_to_line(a1, b1, b2) < 1
            or self._distance_point_to_line(a2, b1, b2) < 1
            or self._distance_point_to_line(b1, a1, a2) < 1
            or self._distance_point_to_line(b2, a1, a2) < 1
        )

    def _apply_pin_component_highlights(self, pin_ids, color_map):
        wires = [it for it in self.scene().items() if isinstance(it, Wire)]
        if not wires:
            return

        # Build wire adjacency once
        adj = {w: [] for w in wires}
        for i, w1 in enumerate(wires):
            for w2 in wires[i + 1 :]:
                if self._wires_connected(w1, w2):
                    adj[w1].append(w2)
                    adj[w2].append(w1)

        for item in self.scene().items():
            if not isinstance(item, SchematicItem) or not hasattr(item, "pins"):
                continue
            for pin_id, info in item.pins.items():
                if str(pin_id) not in pin_ids:
                    continue
                pin_pos = item.mapToScene(info["pos"])
                pin_color = color_map.get(self._canonical_probe_net_name(pin_id))
                if pin_color is None:
                    continue

                starts = [w for w in wires if self._wire_touches_pos(w, pin_pos)]
                stack = list(starts)
                seen = set(starts)
                while stack:
                    curr = stack.pop()
                    if curr.highlight_color is None:
                        curr.highlight_color = pin_color
                        curr.update()
                    for nxt in adj[curr]:
                        if nxt not in seen:
                            seen.add(nxt)
                            stack.append(nxt)

    @staticmethod
    def _distance_point_to_line(point, p1, p2):
        ap = point - p1
        ab = p2 - p1
        len_sq = ab.x() ** 2 + ab.y() ** 2
        if len_sq == 0:
            return (point - p1).manhattanLength()
        t = max(0, min(1, (ap.x() * ab.x() + ap.y() * ab.y()) / len_sq))
        proj = p1 + t * ab
        return (point - proj).manhattanLength()

    def _resolve_probe_net_from_pin(self, sch_item, pin_id, pin_pos):
        # 1) Direct connectivity map lookup for this exact pin
        if (
            hasattr(self, "last_item_to_node")
            and self.last_item_to_node
            and (sch_item, pin_id) in self.last_item_to_node
        ):
            mapped = self.last_item_to_node[(sch_item, pin_id)]
            pseudo = f"{getattr(sch_item, 'name', '')}:{pin_id}"
            if str(mapped).lower() != pseudo.lower():
                return mapped

        # 2) Geometric fallback: nearest connected wire -> mapped net
        nearest_wire = None
        nearest_d = 1e9
        for obj in self.scene().items():
            if not isinstance(obj, Wire):
                continue
            line = obj.line()
            p1 = obj.mapToScene(line.p1())
            p2 = obj.mapToScene(line.p2())
            d = self._distance_point_to_line(pin_pos, p1, p2)
            if d < nearest_d:
                nearest_d = d
                nearest_wire = obj

        if nearest_wire is not None and nearest_d < 2.0:
            if (
                hasattr(self, "last_item_to_node")
                and self.last_item_to_node
                and nearest_wire in self.last_item_to_node
            ):
                return self.last_item_to_node[nearest_wire]
            return nearest_wire.name or nearest_wire.net_name

        # 3) Last-resort pin-like naming without artificial V(...) wrapping
        params = getattr(sch_item, "parameters", {}) or {}
        return params.get("NET_NAME") or sch_item.name

    def _apply_net_highlights_to_open_views(self):
        main_window = self.window()
        if hasattr(main_window, "tabs"):
            for i in range(main_window.tabs.count()):
                widget = main_window.tabs.widget(i)
                if hasattr(widget, "apply_net_highlight_full_names"):
                    widget.apply_net_highlight_full_names()
        else:
            self.apply_net_highlight_full_names()

    def _highlight_selected_net(self):
        selected = [w for w in self.scene().selectedItems() if isinstance(w, Wire)]
        if not selected:
            return
        full_names = {
            self._canonical_probe_net_name(self._get_wire_net_name(w)) for w in selected
        }
        full_names.discard(None)
        if not full_names:
            return

        store_names, color_map = self._get_highlight_store()

        # Assign a random vivid color per net name
        for full_name in full_names:
            if full_name not in color_map:
                h = random.randint(0, 359)
                color = QColor.fromHsvF(h / 360.0, 0.85, 1.0)
                color_map[full_name] = color
        store_names.update(full_names)

        self._apply_net_highlights_to_open_views()

    def _unhighlight_all_nets(self):
        store_names, color_map = self._get_highlight_store()
        store_names.clear()
        color_map.clear()
        self._apply_net_highlights_to_open_views()

    def mousePressEvent(self, event: QMouseEvent):
        from PyQt6.QtCore import Qt

        pos = self.mapToScene(event.position().toPoint())
        # Snap
        pos = QPointF(round(pos.x() / 10) * 10, round(pos.y() / 10) * 10)

        # Right click drag for Zoom-to-Rect
        if event.button() == Qt.MouseButton.RightButton:
            # Ensure zoom_rect_item is alive and in the scene
            try:
                if not self.zoom_rect_item.scene():
                    self.scene().addItem(self.zoom_rect_item)
            except (RuntimeError, AttributeError):
                from PyQt6.QtWidgets import QGraphicsRectItem
                from PyQt6.QtGui import QPen, QColor
                from PyQt6.QtCore import Qt

                self.zoom_rect_item = QGraphicsRectItem()
                self.zoom_rect_item.setPen(
                    QPen(QColor(0, 0, 255), 1, Qt.PenStyle.DashLine)
                )
                self.zoom_rect_item.setBrush(QColor(0, 0, 255, 30))
                self.scene().addItem(self.zoom_rect_item)

            self._old_mode = self.current_mode
            self.set_mode(self.MODE_ZOOM_RECT)
            self.zoom_start_pos = self.mapToScene(event.position().toPoint())
            self.zoom_rect_item.setRect(
                QRectF(self.zoom_start_pos, self.zoom_start_pos)
            )
            self.zoom_rect_item.setVisible(True)
            return
        if self.current_mode == self.MODE_PROBE:
            # Find net under cursor
            items = self.scene().items(pos)
            net_name = None

            # 1. Check for Wire
            for item in items:
                if isinstance(item, Wire):
                    if (
                        hasattr(self, "last_item_to_node")
                        and self.last_item_to_node
                        and item in self.last_item_to_node
                    ):
                        net_name = self.last_item_to_node[item]
                    else:
                        net_name = item.name or "N_?"
                    break

            # 2. Check for Pin
            if not net_name:
                for item in items:
                    if isinstance(item, SchematicItem):
                        for pin_id, info in item.pins.items():
                            pin_pos = item.mapToScene(info["pos"])
                            if (pin_pos - pos).manhattanLength() < 7:
                                net_name = self._resolve_probe_net_from_pin(
                                    item, pin_id, pin_pos
                                )
                                break
                        if net_name:
                            break

            if net_name:
                canon = self._canonical_probe_net_name(net_name)
                if canon:
                    self.netProbed.emit(canon)
            self.set_mode(self.MODE_SELECT)
            return

        if self.current_mode == self.MODE_WIRE:
            if event.button() == Qt.MouseButton.LeftButton:
                if not self.wire_start:
                    self.wire_start = pos
                    self.current_wire = Wire(pos, pos)
                    self.scene().addItem(self.current_wire)
                    self.wire_mode_locked = False
                else:
                    # Finish segment
                    # The current_wire is a temporary visual. We create a new one for the command.

                    start_p = self.wire_start
                    end_p = pos

                    # Logic based on locked mode
                    if self.wire_mode_locked:
                        if self.wire_hv_mode:  # HV
                            corner_p = QPointF(end_p.x(), start_p.y())
                            if corner_p != start_p:
                                cmd = CreateWireCommand(self.scene(), start_p, corner_p)
                                self.undo_stack.push(cmd)
                                start_p = corner_p
                            if corner_p != end_p:
                                cmd = CreateWireCommand(self.scene(), start_p, end_p)
                                self.undo_stack.push(cmd)
                        else:  # VH
                            corner_p = QPointF(start_p.x(), end_p.y())
                            if corner_p != start_p:
                                cmd = CreateWireCommand(self.scene(), start_p, corner_p)
                                self.undo_stack.push(cmd)
                                start_p = corner_p
                            if corner_p != end_p:
                                cmd = CreateWireCommand(self.scene(), start_p, end_p)
                                self.undo_stack.push(cmd)
                    else:
                        # Direct connection (straight line)
                        # This happens if user clicks BEFORE 50px threshold.
                        # We just create a straight wire.
                        if start_p != end_p:
                            cmd = CreateWireCommand(self.scene(), start_p, end_p)
                            self.undo_stack.push(cmd)

                    # Clean up temp wire
                    if self.current_wire:
                        self.scene().removeItem(self.current_wire)
                        self.current_wire = None

                    # Check if we clicked on a pin or another wire to end chain
                    clicked_items = self.scene().items(pos)
                    hit_pin = False
                    for item in clicked_items:
                        if isinstance(item, SchematicItem):
                            # Check distance to pins
                            for pin_id, pin_info in item.pins.items():
                                pin_pos = item.mapToScene(pin_info["pos"])
                                if (
                                    pin_pos - pos
                                ).manhattanLength() < 5:  # Small tolerance
                                    hit_pin = True
                                    break
                            if hit_pin:
                                break  # Found a pin on a schematic item

                    if hit_pin:
                        self.wire_start = None
                        self.set_mode(self.MODE_SELECT)  # Exit wire mode on pin
                    else:
                        # Chain
                        self.wire_start = pos
                        self.current_wire = Wire(pos, pos)
                        self.scene().addItem(self.current_wire)
                        self.wire_mode_locked = False  # Reset for next segment

            elif event.button() == Qt.MouseButton.MiddleButton:
                # Force switch manually if needed, though user relies on auto
                self.wire_hv_mode = not self.wire_hv_mode
                self.wire_mode_locked = True  # Lock it if manually switched
                self.statusMessage.emit(
                    f"Mode: Wire ({'HV' if self.wire_hv_mode else 'VH'})"
                )

            elif event.button() == Qt.MouseButton.RightButton:
                if self.current_wire:
                    self.scene().removeItem(self.current_wire)
                    self.current_wire = None
                self.wire_start = None
                self.set_mode(self.MODE_SELECT)

        elif self.current_mode == self.MODE_LINE:
            if event.button() == Qt.MouseButton.LeftButton:
                if not self.line_start:
                    # Start Line
                    self.line_start = pos
                    self.current_line_item = QGraphicsLineItem(QLineF(pos, pos))
                    # Styling for graphical lines
                    pen = QPen(theme_manager.get_color("line_mode"))
                    pen.setWidth(2)
                    self.current_line_item.setPen(pen)
                    self.scene().addItem(self.current_line_item)
                else:
                    # Finish Line
                    start_p = self.line_start
                    end_p = pos
                    if start_p != end_p:
                        # Create persistent line item
                        line_item = QGraphicsLineItem(QLineF(start_p, end_p))
                        line_item.setFlags(
                            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                        )
                        pen = QPen(theme_manager.get_color("line_mode"))
                        pen.setWidth(2)
                        line_item.setPen(pen)
                        # Add to scene via command
                        cmd = InsertItemsCommand(self.scene(), [line_item])
                        self.undo_stack.push(cmd)

                    # Clean up temp
                    if self.current_line_item:
                        self.scene().removeItem(self.current_line_item)
                        self.current_line_item = None
                    self.line_start = None

        elif self.current_mode == self.MODE_MOVE:
            super().mousePressEvent(event)  # Handle selection
            if event.button() == Qt.MouseButton.LeftButton:
                if not self.move_ref_pos:
                    # Step 1: Click Reference Point
                    self.move_ref_pos = pos

                    # Identify Rubber Band Wires
                    self.rubber_band_data = []
                    # Find pins of selected schematic items
                    for item in self.moving_items:
                        if isinstance(item, SchematicItem):
                            for pin_info in item.pins.values():
                                pin_scene_pos = item.mapToScene(pin_info["pos"])
                                # Find wires connected to this pin (that are NOT moving)
                                # TODO: Optimize spatial search
                                for other_item in self.scene().items(pin_scene_pos):
                                    if (
                                        isinstance(other_item, Wire)
                                        and other_item not in self.moving_items
                                    ):
                                        # Check which end matches
                                        line = other_item.line()
                                        if (
                                            line.p1() - pin_scene_pos
                                        ).manhattanLength() < 2:
                                            self.rubber_band_data.append(
                                                (other_item, 0, QLineF(line))
                                            )
                                        elif (
                                            line.p2() - pin_scene_pos
                                        ).manhattanLength() < 2:
                                            self.rubber_band_data.append(
                                                (other_item, 1, QLineF(line))
                                            )

                else:
                    # Step 2: Click Target Point (Commit)
                    delta = pos - self.move_ref_pos

                    # We moved them visually during mouseMoveEvent.
                    # To use UndoCommand, we should revert the visual move, and let the command do it.
                    # Move back
                    for item in self.moving_items:
                        item.moveBy(-delta.x(), -delta.y())

                    # Revert wires
                    # ... Actually, the wires were modified in mouseMove potentially if we implemented it there.
                    # If we didn't calculate rubberband in mouseMove (visual only), we are fine.
                    # But we want visual feedback.
                    # Let's revert visual rubberband:
                    for wire, idx, original_line in self.rubber_band_data:
                        wire.setLine(original_line)

                    # Prepare Command Data
                    # Rubber band: list of (wire, old_line, new_line)
                    rb_cmd_data = []
                    for wire, idx, original_line in self.rubber_band_data:
                        new_line = QLineF(original_line)
                        if idx == 0:
                            new_line.setP1(new_line.p1() + delta)
                        else:
                            new_line.setP2(new_line.p2() + delta)
                        rb_cmd_data.append((wire, original_line, new_line))

                    cmd = MoveItemsCommand(self.moving_items, delta, rb_cmd_data)
                    self.undo_stack.push(cmd)

                    self.set_mode(self.MODE_SELECT)

        elif self.current_mode == self.MODE_COPY:
            if event.button() == Qt.MouseButton.LeftButton:
                if not self.copy_ref_pos:
                    # Step 1: Pick up origin
                    self.copy_ref_pos = pos
                    if not self.copy_source_items:
                        # If nothing was selected, try to pick up item at cursor
                        # We use a small rect around pos to find items
                        items = self.scene().items(
                            QRectF(pos.x() - 5, pos.y() - 5, 10, 10)
                        )
                        # Filter for parent items (top level)
                        top_items = [
                            it
                            for it in items
                            if it.parentItem() is None
                            and isinstance(it, (SchematicItem, Wire, Junction))
                        ]
                        if top_items:
                            self.copy_source_items = [top_items[0]]

                    if self.copy_source_items:
                        # Create preview clones
                        self.copy_preview_items = self._clone_items(
                            self.copy_source_items, assign_name=False
                        )
                        for item in self.copy_preview_items:
                            self.scene().addItem(item)
                            item.setZValue(1000)  # Ensure they are on top
                            item.setOpacity(0.5)  # Ghostly preview
                        self.statusMessage.emit("Mode: Copy (Click target point)")
                    else:
                        self.copy_ref_pos = None  # Reset if nothing to copy
                else:
                    # Step 2: Place copies
                    delta = pos - self.copy_ref_pos
                    clones = self._clone_items(self.copy_source_items)
                    for clone in clones:
                        clone.moveBy(delta.x(), delta.y())

                    cmd = InsertItemsCommand(self.scene(), clones)
                    self.undo_stack.push(cmd)

                    self.statusMessage.emit(
                        "Mode: Copy (Click target for more, Esc to exit)"
                    )

            elif event.button() == Qt.MouseButton.RightButton:
                self.set_mode(self.MODE_SELECT)

        else:
            # Store initial positions for undo
            self._move_start_positions = {
                item: item.pos()
                for item in self.scene().selectedItems()
                if item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            }
            super().mousePressEvent(event)
            # If nothing was selected before, check if something is selected now
            if not self._move_start_positions:
                self._move_start_positions = {
                    item: item.pos()
                    for item in self.scene().selectedItems()
                    if item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                }

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        # Allow base class (and thus items) to handle it first
        super().mouseDoubleClickEvent(event)
        if event.isAccepted():
            return

        # Not handled by an item? Check for net plotting.
        pos = self.mapToScene(event.position().toPoint())
        items = self.scene().items(pos)

        # 1. Check for Wire
        for item in items:
            if isinstance(item, Wire):
                # Try last simulation mapping first, then item.name
                name = self.last_item_to_node.get(item) or item.name
                if name:
                    self.netSignalsPlotRequested.emit(name)
                    event.accept()
                    return

        # 2. Check for Pin of SchematicItem
        for item in items:
            if hasattr(item, "pins") and isinstance(item.pins, dict):
                # Check each pin's distance
                for pid, info in item.pins.items():
                    try:
                        pin_scene = item.mapToScene(info["pos"])
                        if (pin_scene - pos).manhattanLength() < 10:
                            # Found a pin. Now find a wire connected to it.
                            pin_ref = (item, pid)
                            name = self.last_item_to_node.get(pin_ref)
                            if name:
                                self.netSignalsPlotRequested.emit(name)
                                event.accept()
                                return

                            for neighbor in self.scene().items(pin_scene):
                                if isinstance(neighbor, Wire):
                                    name = (
                                        self.last_item_to_node.get(neighbor)
                                        or neighbor.name
                                    )
                                    if name:
                                        self.netSignalsPlotRequested.emit(name)
                                        event.accept()
                                        return
                    except Exception:
                        continue
            elif hasattr(item, "pin_items") and isinstance(item.pin_items, dict):
                for pid, pin_obj in item.pin_items.items():
                    try:
                        r = pin_obj.rect()
                        pin_scene = pin_obj.mapToScene(r.center())
                        if (pin_scene - pos).manhattanLength() < 10:
                            pin_ref = (item, pid)
                            name = self.last_item_to_node.get(pin_ref)
                            if name:
                                self.netSignalsPlotRequested.emit(name)
                                event.accept()
                                return

                            for neighbor in self.scene().items(pin_scene):
                                if isinstance(neighbor, Wire):
                                    name = (
                                        self.last_item_to_node.get(neighbor)
                                        or neighbor.name
                                    )
                                    if name:
                                        self.netSignalsPlotRequested.emit(name)
                                        event.accept()
                                        return
                    except Exception:
                        continue

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self.current_mode == self.MODE_ZOOM_RECT:
            rect = self.zoom_rect_item.rect()
            self.zoom_rect_item.setVisible(False)
            self.set_mode(getattr(self, "_old_mode", self.MODE_SELECT))
            if rect.width() > 5 and rect.height() > 5:
                self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            return

        if self.current_mode == self.MODE_SELECT:
            # Check if any items moved and commit to undo stack
            moved_data = []
            for item, start_pos in getattr(self, "_move_start_positions", {}).items():
                if item.pos() != start_pos:
                    delta = item.pos() - start_pos
                    moved_data.append((item, start_pos, delta))

            if moved_data:
                # Group by delta (usually they all move by the same amount if dragged together)
                # For simplicity, we assume they move together if they were selected together
                # We'll use the delta from the first item
                items = [d[0] for d in moved_data]
                delta = moved_data[0][2]

                # Snap the final positions to grid and adjust delta
                # Actually delta should already be snapped if items were snapped.

                # Revert visually for the command to take over
                for item, start_pos, _ in moved_data:
                    item.setPos(start_pos)

                # Push MoveItemsCommand
                from opens_suite.commands import MoveItemsCommand

                cmd = MoveItemsCommand(items, delta, [])
                self.undo_stack.push(cmd)

            self._move_start_positions = {}

        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        scene_pos = self.mapToScene(event.position().toPoint())

        if self.current_mode == self.MODE_ZOOM_RECT:
            rect = QRectF(self.zoom_start_pos, scene_pos).normalized()
            self.zoom_rect_item.setRect(rect)
            return

        snapped_pos = self.snap_to_grid(scene_pos)

        if self.current_mode == self.MODE_WIRE:
            if self.wire_start:
                path = QPainterPath(self.wire_start)

                # Check for lock threshold
                if not self.wire_mode_locked:
                    diff = snapped_pos - self.wire_start
                    dist = (diff.x() ** 2 + diff.y() ** 2) ** 0.5
                    if dist > 10:
                        self.wire_mode_locked = True
                        # Determine HV vs VH
                        if abs(diff.x()) > abs(diff.y()):
                            self.wire_hv_mode = True  # Horizontal first
                        else:
                            self.wire_hv_mode = False  # Vertical first

                if not self.wire_mode_locked:
                    # Straight Line Preview
                    path.lineTo(snapped_pos)
                else:
                    # L-Shape Preview
                    if self.wire_hv_mode:
                        path.lineTo(snapped_pos.x(), self.wire_start.y())
                        path.lineTo(snapped_pos)
                    else:
                        path.lineTo(self.wire_start.x(), snapped_pos.y())
                        path.lineTo(snapped_pos)

                self.wire_preview_path.setPath(path)
                if not self.wire_preview_path.isVisible():
                    self.wire_preview_path.setVisible(True)

        elif self.current_mode == self.MODE_LINE:
            # Defensive: only update preview line if we have a valid start point
            if self.current_line_item and self.line_start is not None:
                self.current_line_item.setLine(QLineF(self.line_start, snapped_pos))

        elif self.current_mode == self.MODE_MOVE:
            if self.move_ref_pos:
                delta = snapped_pos - self.move_ref_pos

                # Visual Feedback: Move items
                # Warning: We are accumulating delta if we use moveBy repeatedly relative to self.move_ref_pos
                # Logic: Reset to ref, then move to new?
                # Better: track 'last_pos' and moveBy(diff)

                # ... implementing incremental move
                # Need to update ref_pos or track delta from start.
                # Let's track delta from start.
                # But mouseMove provides absolute pos.

                # Simplify: Just don't do real-time feedback for rubber bands perfectly OR
                # restore state every frame? Expensive.
                # Incremental approach:
                # self.current_pos (last frame)

                # OK, simplest for now:
                # We won't do full rubber band visual feedback in this iteration to insure stability,
                # we just move the items.
                last_pos = getattr(self, "last_move_pos", self.move_ref_pos)
                frame_delta = snapped_pos - last_pos

                for item in self.moving_items:
                    item.moveBy(frame_delta.x(), frame_delta.y())

                # Rubber band visual update?
                for wire, idx, original_line in self.rubber_band_data:
                    # Update wire endpoints to follow pins
                    # For now just call recalculate_pin_connectivity for red marker updates
                    pass

                self._update_pin_connectivity()
                self.last_move_pos = snapped_pos

        elif self.current_mode == self.MODE_COPY:
            if self.copy_ref_pos and self.copy_preview_items:
                delta = snapped_pos - self.copy_ref_pos
                # Reset to source positions before applying current delta
                for preview, source in zip(
                    self.copy_preview_items, self.copy_source_items
                ):
                    preview.setPos(source.pos() + delta)

        elif self.current_mode == self.MODE_SELECT:
            if self.scene().mouseGrabberItem():
                self._update_pin_connectivity()

        super().mouseMoveEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        path = event.mimeData().text()
        # Support two types of drops: file-based SVG symbols and programmatic PCELLs
        if path.startswith("PCELL:"):
            # Programmatic pcell instantiation
            try:
                from opens import pcell as _pcell

                name = path.split(":", 1)[1]
                cls = _pcell.PCELL_REGISTRY.get(name)
                if cls:
                    item = cls(parameters={})
                    scene_pos = self.mapToScene(event.position().toPoint())
                    item.setPos(self.snap_to_grid(scene_pos))

                    # Assign a generated name only if the item provides the
                    # expected naming interface (prefix and set_name).
                    try:
                        if hasattr(item, "prefix") and callable(
                            getattr(item, "set_name", None)
                        ):
                            self._assign_name(item)
                    except Exception:
                        # Be defensive: don't block insertion if naming fails.
                        pass

                    from opens_suite.commands import InsertItemsCommand

                    cmd = InsertItemsCommand(self.scene(), item)
                    self.undo_stack.push(cmd)

                    event.acceptProposedAction()
                    return
            except Exception:
                pass

        # Fallback: treat text as a filesystem path for SVG symbols
        if os.path.exists(path):
            item = SchematicItem(path)
            scene_pos = self.mapToScene(event.position().toPoint())
            item.setPos(self.snap_to_grid(scene_pos))

            self._assign_name(item)
            self._connect_item(item)

            from opens_suite.commands import InsertItemsCommand

            cmd = InsertItemsCommand(self.scene(), item)
            self.undo_stack.push(cmd)

            event.acceptProposedAction()

    def _assign_name(self, item):
        prefix = item.prefix
        indices = []
        for i in self.scene().items():
            # Include programmatic items that expose a prefix attribute
            if hasattr(i, "prefix") and getattr(i, "prefix") == prefix and i != item:
                name = i.name
                if name.startswith(prefix):
                    try:
                        idx = int(name[len(prefix) :])
                        indices.append(idx)
                    except ValueError:
                        pass

        max_idx = max(indices) if indices else 0
        new_name = f"{prefix}{max_idx + 1}"
        item.set_name(new_name)

    def _clone_item(self, item, assign_name=True):
        """Creates a deep-ish clone of a schematic item or wire."""
        if isinstance(item, SchematicItem):
            clone = SchematicItem(item.svg_path)
            clone.setPos(item.pos())
            clone.setTransform(item.transform())
            # Important: custom attributes like rotation_angle if they exist
            if hasattr(item, "rotation_angle"):
                clone.rotation_angle = item.rotation_angle

            if hasattr(item, "parameters"):
                clone.parameters = item.parameters.copy()

            # Refresh visuals
            clone._update_labels()
            clone._update_svg()

            if assign_name:
                # Assign a NEW name to avoid collisions
                self._assign_name(clone)
            else:
                clone.name = getattr(item, "name", "")
                clone._update_labels()

            self._connect_item(clone)
            return clone

        elif isinstance(item, Wire):
            l = item.line()
            p1 = item.mapToScene(l.p1())
            p2 = item.mapToScene(l.p2())
            clone = Wire(p1, p2)
            if item.name:
                clone.name = item.name
            return clone

        elif isinstance(item, Junction):
            center = item.mapToScene(item.rect().center())
            clone = Junction(center)
            return clone

        return None

    def _clone_items(self, items, assign_name=True):
        """Clones a list of items and returns the clones."""
        return [
            cl
            for cl in [self._clone_item(it, assign_name=assign_name) for it in items]
            if cl is not None
        ]

    def _transform_selection(self, mode="rotate"):
        """Rotates or mirrors the current selection around its center."""
        items = [it for it in self.scene().selectedItems() if it.parentItem() is None]
        if not items:
            return

        # 1. Calculate bounding rect in scene coords
        rect = items[0].sceneBoundingRect()
        for it in items[1:]:
            rect = rect.united(it.sceneBoundingRect())

        # 2. Get center and snap it
        center = rect.center()
        center = self.snap_to_grid(center)

        from PyQt6.QtGui import QTransform
        from opens_suite.commands import TransformItemsCommand

        old_state = {}
        new_state = {}

        for it in items:
            # Current state
            t = it.transform()
            old_pos = it.scenePos()
            old_line = it.line() if hasattr(it, "line") else None

            old_data = [old_pos, (t.m11(), t.m12(), t.m21(), t.m22(), t.dx(), t.dy())]
            if old_line:
                old_data.append(QLineF(old_line))
            old_state[it] = tuple(old_data)

            # Calculate new
            rel_pos = old_pos - center

            if mode == "rotate":
                # Position rotation
                new_rel_pos = QPointF(-rel_pos.y(), rel_pos.x())
                # Local transform rotation
                rot_t = QTransform().rotate(90)
                new_t = rot_t * t
            else:  # mirror
                # Position mirroring
                new_rel_pos = QPointF(-rel_pos.x(), rel_pos.y())
                # Local transform mirroring
                mirror_t = QTransform(-1, 0, 0, 1, 0, 0)
                new_t = mirror_t * t

            # Base new position (un-snapped yet, will snap below)
            raw_new_pos = center + new_rel_pos

            if isinstance(it, Wire):
                # For wires, we want to convert the transform into line endpoints
                # and snap them to ensure they are on grid.
                temp_w = Wire(old_line.p1(), old_line.p2())
                temp_w.setPos(raw_new_pos)
                temp_w.setTransform(new_t)

                p1_s = self.snap_to_grid(temp_w.mapToScene(old_line.p1()))
                p2_s = self.snap_to_grid(temp_w.mapToScene(old_line.p2()))

                # New state for wire: pos (0,0), identity transform, updated line
                new_state[it] = (
                    QPointF(0, 0),
                    (1, 0, 0, 1, 0, 0),  # Identity
                    QLineF(p1_s, p2_s),
                )
            else:
                # For components, just snap the position and keep the transform
                new_state[it] = (
                    self.snap_to_grid(raw_new_pos),
                    (
                        new_t.m11(),
                        new_t.m12(),
                        new_t.m21(),
                        new_t.m22(),
                        new_t.dx(),
                        new_t.dy(),
                    ),
                )

        cmd = TransformItemsCommand(items, old_state, new_state)
        self.undo_stack.push(cmd)
