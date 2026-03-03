"""PCell support: base symbol class and a programmable cell (pcell) implementation.

This module provides:
- SymbolBase: a minimal base class (non-GUI) describing a symbol's parameters.
- PCellSymbol: a QGraphicsObject that renders a rectangle with a column of pins on
  the right side. Pins can be defined via a parameter (e.g. 'PINS' = 'PB0 PB1 PB2').
- PCELL_REGISTRY and register_pcell() to allow manual registration of pcell classes.

This is additive and should not change existing SVG-based symbols.
"""

from typing import Dict, List
from PyQt6.QtWidgets import QGraphicsObject, QGraphicsRectItem, QGraphicsItem
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont
from PyQt6.QtCore import QRectF, QPointF, Qt
from PyQt6.QtWidgets import QInputDialog


PCELL_REGISTRY: Dict[str, type] = {}


def register_pcell(name: str, cls: type) -> None:
    """Register a pcell class under a name.

    Example: register_pcell("python_block", PCellSymbol)
    """
    PCELL_REGISTRY[name] = cls


class SymbolBase:
    """Minimal non-GUI base describing parameters and name.

    Subclasses may implement GUI by composing or inheriting this class.
    """

    def __init__(self, parameters: Dict[str, str] = None):
        self.parameters = parameters.copy() if parameters else {}
        # Ensure MODELNAME key exists so UIs and serializers can always find it
        self.parameters.setdefault("MODELNAME", "")
        # instance name is managed by the scene (via set_name);
        # do not initialize the instance name from MODELNAME to avoid
        # conflating the instance name with the model identifier.
        self.name = ""

    def set_parameter(self, name: str, value: str) -> None:
        self.parameters[name] = value

    def get_parameter(self, name: str, default: str = "") -> str:
        return self.parameters.get(name, default)

    def set_parameters(self, params: Dict[str, str]) -> None:
        self.parameters.update(params)


class PCellSymbol(QGraphicsObject, SymbolBase):
    """A programmable cell drawn as a rectangle with pins on the right column.

    Parameters are read from a parameter named 'PINS' (space-separated) by default.
    """

    def __init__(self, parameters: Dict[str, str] = None, parent=None):
        QGraphicsObject.__init__(self, parent)
        SymbolBase.__init__(self, parameters=parameters)

        # Use the QGraphicsItem flag enum values to set item behavior
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )

        # Visual and layout
        self.width = 180
        self.pin_spacing = 18
        self.left_margin = 8
        self.top_margin = 12
        self.pin_size = 8

        self.pins: List[str] = []
        self.pin_items: Dict[str, QGraphicsRectItem] = {}
        self.connected_pins: List[str] = []

        # Naming/prefix used by the schematic for automatic instance names
        # Provide sensible defaults so _assign_name in SchematicView can operate
        # on programmatic pcells just like SVG-based SchematicItem instances.
        self.prefix = self.get_parameter("PREFIX", "A")
        # self.name is managed by SymbolBase (initialized from MODELNAME)
        if not getattr(self, "name", None):
            self.name = ""

        # parse initial pins
        # Ensure the PINS parameter exists (space-separated string)
        if "PINS" not in self.parameters and "pins" not in self.parameters:
            self.parameters["PINS"] = ""

        pins_raw = self.get_parameter("PINS", self.get_parameter("pins", ""))
        if not pins_raw:
            # fallback: maybe parameters specify explicit numbered pins
            pins_raw = self.get_parameter("PB", "")

        self._set_pins_from_string(pins_raw)

    def boundingRect(self) -> QRectF:
        height = max(40, self.top_margin * 2 + len(self.pins) * self.pin_spacing)
        return QRectF(0, 0, self.width, height)

    def paint(self, painter: QPainter, option, widget) -> None:
        rect = self.boundingRect()
        painter.setPen(QPen(QColor("black"), 1))
        painter.setBrush(QBrush(QColor("#f0f0f0")))
        painter.drawRect(rect)

        # Draw instance name (assigned by the scene) at top-left. Draw the
        # MODELNAME (model identifier) as a smaller secondary label so the
        # two are visually distinct.
        painter.setPen(QPen(QColor("black")))
        font = QFont("Arial", 10)
        painter.setFont(font)
        inst_name = self.name or "PCELL"
        painter.drawText(QPointF(self.left_margin, 12), inst_name)

        modelname = self.get_parameter("MODELNAME", "")
        if modelname:
            small_font = QFont("Arial", 8)
            painter.setFont(small_font)
            painter.setPen(QPen(QColor("#333333")))
            painter.drawText(QPointF(self.left_margin, 26), modelname)

        # Draw pin labels on the right side; the actual pin rectangles are
        # represented by QGraphicsRectItem children (self.pin_items). We hide
        # labels for pins that are connected (self.connected_pins) so the UI
        # matches the behavior of SVG-based items.
        width = rect.width()
        for idx, pin in enumerate(self.pins):
            # Skip labels for connected pins
            if hasattr(self, "connected_pins") and pin in getattr(
                self, "connected_pins", []
            ):
                continue
            pin_item = self.pin_items.get(pin)
            if pin_item is not None:
                local_y = pin_item.pos().y()
            else:
                local_y = self.top_margin + idx * self.pin_spacing
            px = width - self.pin_size
            # label left of the pin square
            text_x = px - 6 - painter.fontMetrics().horizontalAdvance(pin)
            painter.drawText(QPointF(text_x, local_y + self.pin_size), pin)

        # Also render a compact list of pin names on the left inside the box
        if self.pins:
            painter.setPen(QPen(QColor("black")))
            small_font = QFont("Arial", 8)
            painter.setFont(small_font)
            for idx, pin in enumerate(self.pins):
                ty = self.top_margin + idx * (self.pin_spacing - 2) + 4
                painter.drawText(QPointF(self.left_margin, ty + 12), pin)
        else:
            # Hint for editing pins
            hint_font = QFont("Arial", 8)
            hint_font.setItalic(True)
            painter.setFont(hint_font)
            painter.setPen(QPen(QColor("#666666")))
            painter.drawText(
                QPointF(self.left_margin, rect.height() - 8),
                "Double-click to edit PINS",
            )

    def _set_pins_from_string(self, s: str) -> None:
        """Set pins from a whitespace-separated string and create pin graphics.

        Existing pin items are removed and recreated.
        """
        s = (s or "").strip()
        if not s:
            self.pins = []
        else:
            self.pins = [tok for tok in s.split() if tok]

        # Remove existing pin items
        for item in list(self.pin_items.values()):
            try:
                item.setParentItem(None)
                item.scene().removeItem(item)
            except Exception:
                pass
        self.pin_items.clear()

        # Create new pin QGraphicsRectItem children to support connectivity searches
        for idx, pin in enumerate(self.pins):
            rect = QGraphicsRectItem(self)
            rect.setRect(0, 0, self.pin_size, self.pin_size)
            rect.setBrush(QBrush(QColor("red")))
            rect.setPen(QPen(Qt.PenStyle.NoPen))
            # position will be updated in update_pin_positions
            rect.setData(Qt.ItemDataRole.UserRole, pin)
            self.pin_items[pin] = rect

        self.update_pin_positions()
        self.update()

    def update_pin_positions(self) -> None:
        rect = self.boundingRect()
        width = rect.width()
        scene = self.scene()
        # Determine grid size (fallback to 10 if scene doesn't provide it)
        grid = getattr(scene, "grid_size", 20) if scene is not None else 20
        for idx, pin in enumerate(self.pins):
            # desired local coordinates for the pin's top-left
            local_y = self.top_margin + idx * self.pin_spacing
            local_x = width - self.pin_size

            # Compute the pin center in local coordinates
            local_center = QPointF(
                local_x + self.pin_size / 2.0, local_y + self.pin_size / 2.0
            )

            # Map to scene, snap the scene Y coordinate to grid, then map back
            try:
                scene_center = self.mapToScene(local_center)
                snapped_scene_center = QPointF(
                    scene_center.x(), round(scene_center.y() / grid) * grid
                )
                final_local_center = self.mapFromScene(snapped_scene_center)
                # Compute top-left local from center
                final_local_topleft = QPointF(
                    final_local_center.x() - self.pin_size / 2.0,
                    final_local_center.y() - self.pin_size / 2.0,
                )
            except Exception:
                # Fallback: fall back to previous heuristic based on item pos
                scene_pin_center_y = self.pos().y() + local_y + self.pin_size / 2
                snapped_center_y = round(scene_pin_center_y / grid) * grid
                final_local_topleft = QPointF(
                    local_x, snapped_center_y - self.pos().y() - self.pin_size / 2
                )

            item = self.pin_items.get(pin)
            if item:
                # Keep the rect local to the pin item and use setPos for placement
                item.setRect(0, 0, self.pin_size, self.pin_size)
                item.setParentItem(self)
                # Shift pins slightly to the right so the visual square overlaps
                # the symbol border and aligns with the scene grid. Some scenes
                # use different coordinate origins; adding half the symbol width
                # compensates and places the pin marker exactly on the border.
                try:
                    shift_x = self.pin_size / 2.0
                    item.setPos(final_local_topleft + QPointF(shift_x, 0))
                except Exception:
                    item.setPos(final_local_topleft)

    def set_parameter(self, name: str, value: str) -> None:
        SymbolBase.set_parameter(self, name, value)
        # respond to pins parameter changes
        if name.lower() in ("pins", "pids", "pins_list", "p") or name.upper() == "PINS":
            self._set_pins_from_string(value)
        # Do not map MODELNAME to the instance name. MODELNAME is the model
        # identifier (e.g. transistor model) and must remain separate from the
        # instance name (which is assigned by the scene via set_name()).
        self.update()

    def itemChange(self, change, value):
        """Snap item position so symbol borders and pin locations fall on the scene grid.

        Additionally, after the position has been changed, update pin positions so
        the pin QGraphicsRectItem children stay correctly aligned.
        """
        if (
            change == QGraphicsItem.GraphicsItemChange.ItemPositionChange
            and self.scene()
        ):
            grid = getattr(self.scene(), "grid_size", 20)
            new_pos = value
            # Snap Y to grid
            y = round(new_pos.y() / grid) * grid
            # Snap X such that the right border (x + width) lies on grid
            width = self.boundingRect().width()
            right = new_pos.x() + width
            snapped_right = round(right / grid) * grid
            x = snapped_right - width
            return QPointF(x, y)

        if change == QGraphicsItem.GraphicsItemChange.ItemSceneHasChanged:
            scene = self.scene()
            if scene:
                grid = getattr(scene, "grid_size", 20)
                pos = self.pos()
                y = round(pos.y() / grid) * grid
                width = self.boundingRect().width()
                right = pos.x() + width
                x = round(right / grid) * grid - width
                if QPointF(x, y) != pos:
                    self.setPos(x, y)

            try:
                self.update_pin_positions()
            except Exception:
                pass

        if change in (
            QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged,
            QGraphicsItem.GraphicsItemChange.ItemRotationHasChanged,
            QGraphicsItem.GraphicsItemChange.ItemTransformHasChanged,
        ):
            try:
                self.update_pin_positions()
            except Exception:
                pass

        return super().itemChange(change, value)

    def set_name(self, new_name: str) -> None:
        """Set the instance name for this pcell (compatible with SchematicView._assign_name)."""
        # Only set the instance name. Do NOT overwrite MODELNAME: the model
        # identifier is independent from the instance name (e.g. model M1 vs A1).
        self.name = new_name

    def set_parameters(self, params: Dict[str, str]) -> None:
        SymbolBase.set_parameters(self, params)
        # If PINS present, update
        if "PINS" in params or "pins" in params:
            pins_val = params.get("PINS") or params.get("pins")
            self._set_pins_from_string(pins_val)

    def set_connected_pins(self, pin_ids):
        """Hide pin graphics for pins that are connected (like SchematicItem)."""
        for pid, item in self.pin_items.items():
            try:
                item.setVisible(pid not in pin_ids)
            except Exception:
                pass
        # remember connected pins for paint-time decisions
        try:
            self.connected_pins = list(pin_ids)
        except Exception:
            self.connected_pins = []
        self.update()

    def format_netlist(self, item_node_map: dict):
        """Return a netlist line (or list of lines) for this pcell.

        The default implementation returns a simple line using the instance
        name, a bracketed list of pin identifiers, and the MODELNAME parameter
        (falling back to 'python_block'). Advanced pcells may override this
        method to emit arbitrary lines. The mapping `item_node_map` is
        provided as a helper: keys are (item, pin_id) -> node name.
        """
        try:
            # Prefer actual net names for each pin using the provided mapping
            pin_nodes = []
            for pid in self.pins:
                node = item_node_map.get((self, pid))
                if not node:
                    node = f"N_float_{self.name}_{pid}"
                pin_nodes.append(node)

            pins_str = " ".join(pin_nodes)
            modelname = self.get_parameter("MODELNAME", None)
            if not modelname:
                modelname = "python_block"
            return f"A{self.name} [{pins_str}] {modelname}"
        except Exception:
            return f"* Error formatting pcell {getattr(self, 'name', '<unnamed>')}"

    def mouseDoubleClickEvent(self, event):
        # Quick editor for PINS parameter
        current = self.get_parameter("PINS", "")
        text, ok = QInputDialog.getText(
            None, "Edit PINS", "PINS (space-separated):", text=current
        )
        if ok:
            self.set_parameter("PINS", text)
        else:
            super().mouseDoubleClickEvent(event)


# Example: register the generic PCellSymbol under a name for convenience
register_pcell("python_generic", PCellSymbol)
