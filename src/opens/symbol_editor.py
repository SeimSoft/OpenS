import os
import xml.etree.ElementTree as ET
from xml.dom import minidom
from PyQt6.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsRectItem,
    QGraphicsLineItem,
    QGraphicsEllipseItem,
    QGraphicsSimpleTextItem,
    QGraphicsItem,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QLineF, QLine
from PyQt6.QtGui import QPen, QBrush, QColor, QFont, QPainter, QCursor
from opens.theme import theme_manager


class SymbolScene(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid_size = 10
        self.setSceneRect(-1000, -1000, 2000, 2000)
        self.apply_theme()
        theme_manager.themeChanged.connect(self.apply_theme)

    def apply_theme(self):
        self.setBackgroundBrush(theme_manager.get_color("background_schematic"))
        self.grid_color = theme_manager.get_color("grid_dots")
        self.update()

    def apply_theme(self):
        self.setBackgroundBrush(theme_manager.get_color("background_schematic"))
        self.grid_color = theme_manager.get_color("grid_dots")
        self.update()

    def drawBackground(self, painter, rect):
        bg_brush = self.backgroundBrush()
        painter.fillRect(rect, bg_brush)

        left = int(rect.left()) - (int(rect.left()) % self.grid_size)
        top = int(rect.top()) - (int(rect.top()) % self.grid_size)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.grid_color)
        dot_size = 1.5

        for x in range(left, int(rect.right()) + self.grid_size, self.grid_size):
            for y in range(top, int(rect.bottom()) + self.grid_size, self.grid_size):
                painter.drawEllipse(QPointF(x, y), dot_size / 2, dot_size / 2)


class DraggableItem:
    def snap_to_grid(self, grid_size=10):
        pos = self.pos()
        x = round(pos.x() / grid_size) * grid_size
        y = round(pos.y() / grid_size) * grid_size
        self.setPos(x, y)


class ResizeHandle(QGraphicsRectItem):
    """Handle for resizing items."""

    def __init__(self, parent, nx, ny):
        # nx, ny are in [0, 0.5, 1]
        super().__init__(-2, -2, 4, 4, parent)
        self.nx = nx
        self.ny = ny
        self.setBrush(QBrush(QColor("white")))
        self.setPen(QPen(QColor("blue"), 0.5))
        # Important: Don't set ItemIsMovable on handles, otherwise the parent moves.
        # We handle movement manually.
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setZValue(1000)
        self.setAcceptHoverEvents(True)
        self._update_cursor()
        self.hide()
        self.is_dragging = False

    def _update_cursor(self):
        if (self.nx == 0 and self.ny == 0) or (self.nx == 1 and self.ny == 1):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif (self.nx == 1 and self.ny == 0) or (self.nx == 0 and self.ny == 1):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif self.nx == 0.5:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeHorCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = True
            # Store initial positions for manual drag
            self.drag_start_pos = event.scenePos()
            self.initial_rect = self.parentItem().rect()
            self.initial_pos = self.parentItem().pos()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_dragging:
            delta = event.scenePos() - self.drag_start_pos
            # Snap delta to grid for the handle movement
            dx = round(delta.x() / 10) * 10
            dy = round(delta.y() / 10) * 10

            self.parentItem()._on_handle_dragged(
                self, dx, dy, self.initial_rect, self.initial_pos
            )
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.is_dragging:
            self.is_dragging = False
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    # Remove itemChange since we don't use ItemIsMovable anymore
    def itemChange(self, change, value):
        return super().itemChange(change, value)


class SvgRectItem(QGraphicsRectItem, DraggableItem):

    def __init__(self, elem, parent=None):
        super().__init__(parent)
        self.elem = elem
        self.name = "Rectangle"
        self.parameters = {}
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges)

        x = float(elem.get("x", "0"))
        y = float(elem.get("y", "0"))
        w = float(elem.get("width", "0"))
        h = float(elem.get("height", "0"))
        self.setRect(0, 0, w, h)
        self.setPos(x, y)
        self.setPen(
            QPen(
                QColor(elem.get("stroke", "black")),
                float(elem.get("stroke-width", "2")),
            )
        )
        fill = elem.get("fill", "none")
        if fill != "none":
            self.setBrush(QBrush(QColor(fill)))

        self._in_resize_update = False
        self.handles = []
        for ny in [0, 0.5, 1]:
            for nx in [0, 0.5, 1]:
                if nx == 0.5 and ny == 0.5:
                    continue
                h = ResizeHandle(self, nx, ny)
                self.handles.append(h)
        self._update_handle_positions()

    def _update_handle_positions(self):
        self._in_resize_update = True
        r = self.rect()
        for h in self.handles:
            h.setPos(r.x() + h.nx * r.width(), r.y() + h.ny * r.height())
        self._in_resize_update = False

    def _on_handle_dragged(self, handle, dx, dy, initial_rect, initial_pos):
        # px, py is the initial scene position of the item
        px, py = initial_pos.x(), initial_pos.y()
        w, h = initial_rect.width(), initial_rect.height()

        new_x, new_y = px, py
        new_w, new_h = w, h

        if handle.nx == 0:
            new_x = px + dx
            new_w = w - dx
        elif handle.nx == 1:
            new_w = w + dx

        if handle.ny == 0:
            new_y = py + dy
            new_h = h - dy
        elif handle.ny == 1:
            new_h = h + dy

        # Minimum size constraint (10px grid)
        if new_w < 10:
            if handle.nx == 0:
                new_x = px + w - 10
            new_w = 10
        if new_h < 10:
            if handle.ny == 0:
                new_y = py + h - 10
            new_h = 10

        self.setPos(new_x, new_y)
        self.setRect(0, 0, new_w, new_h)
        self._update_handle_positions()

    def itemChange(self, change, value):
        if change == QGraphicsRectItem.GraphicsItemChange.ItemPositionHasChanged:
            self.snap_to_grid()
        elif change == QGraphicsRectItem.GraphicsItemChange.ItemSelectedChange:
            for h in self.handles:
                h.setVisible(bool(value))
        return super().itemChange(change, value)

    def update_elem(self):
        self.elem.set("x", str(self.pos().x()))
        self.elem.set("y", str(self.pos().y()))
        self.elem.set("width", str(self.rect().width()))
        self.elem.set("height", str(self.rect().height()))


class SvgLineItem(QGraphicsLineItem, DraggableItem):
    def __init__(self, elem, parent=None):
        super().__init__(parent)
        self.elem = elem
        self.name = "Line"
        self.parameters = {}
        self.setFlag(QGraphicsLineItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsLineItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsLineItem.GraphicsItemFlag.ItemSendsGeometryChanges)

        # Draw the line relative to its bounds, move to its true position
        x1 = float(elem.get("x1", "0"))
        y1 = float(elem.get("y1", "0"))
        x2 = float(elem.get("x2", "0"))
        y2 = float(elem.get("y2", "0"))

        self.setLine(0, 0, x2 - x1, y2 - y1)
        self.setPos(x1, y1)

        pen = QPen(
            QColor(elem.get("stroke", "black")), float(elem.get("stroke-width", "2"))
        )
        self.setPen(pen)

    def itemChange(self, change, value):
        if change == QGraphicsLineItem.GraphicsItemChange.ItemPositionHasChanged:
            self.snap_to_grid()
        return super().itemChange(change, value)

    def update_elem(self):
        dx = self.pos().x()
        dy = self.pos().y()
        self.elem.set("x1", str(dx))
        self.elem.set("y1", str(dy))
        self.elem.set("x2", str(dx + self.line().x2()))
        self.elem.set("y2", str(dy + self.line().y2()))


class SvgCircleItem(QGraphicsEllipseItem, DraggableItem):
    def __init__(self, elem, parent=None):
        super().__init__(parent)
        self.elem = elem
        self.name = elem.get("id", "Pin")
        self.parameters = {}
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemSendsGeometryChanges)

        cx = float(elem.get("cx", "0"))
        cy = float(elem.get("cy", "0"))
        r = float(elem.get("r", "2"))

        # Ellipse is defined by top-left rect, so move there
        self.setRect(-r, -r, 2 * r, 2 * r)
        self.setPos(cx, cy)

        stroke = elem.get("stroke", "none")
        if stroke != "none":
            self.setPen(QPen(QColor(stroke)))
        else:
            self.setPen(QPen(Qt.PenStyle.NoPen))

        fill = elem.get("fill", "none")
        if fill != "none":
            self.setBrush(QBrush(QColor(fill)))

    def set_name(self, new_name):
        self.name = new_name
        self.elem.set("id", new_name)

    def itemChange(self, change, value):
        if change == QGraphicsEllipseItem.GraphicsItemChange.ItemPositionHasChanged:
            self.snap_to_grid()
        return super().itemChange(change, value)

    def update_elem(self):
        self.elem.set("cx", str(self.pos().x()))
        self.elem.set("cy", str(self.pos().y()))


class SvgTextItem(QGraphicsSimpleTextItem, DraggableItem):
    def __init__(self, elem, parent=None):
        super().__init__(parent)
        self.elem = elem
        self.name = "Text"
        self.parameters = {"CONTENT": elem.text or ""}
        self.setFlag(QGraphicsSimpleTextItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsSimpleTextItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsSimpleTextItem.GraphicsItemFlag.ItemSendsGeometryChanges)

        self.setText(elem.text or "")
        font = QFont("Arial", 8)
        self.setFont(font)

        x = float(elem.get("x", "0"))
        y = float(elem.get("y", "0"))

        # Center alignment approximations
        rect = self.boundingRect()

        anchor = elem.get("text-anchor", "start")
        if "text-anchor" in elem.get("style", ""):
            if "middle" in elem.get("style", ""):
                anchor = "middle"
            elif "end" in elem.get("style", ""):
                anchor = "end"

        if anchor == "middle":
            x -= rect.width() / 2
        elif anchor == "end":
            x -= rect.width()

        self.setPos(x, y - rect.height() * 0.75)

        fill = elem.get("fill", "black")
        self.setBrush(QBrush(QColor(fill)))

    def set_parameter(self, name, value):
        if name == "CONTENT":
            self.parameters["CONTENT"] = value
            self.setText(value)
            self.elem.text = value

    def itemChange(self, change, value):
        if change == QGraphicsSimpleTextItem.GraphicsItemChange.ItemPositionHasChanged:
            self.snap_to_grid(grid_size=5)  # Half grid snap for text
        return super().itemChange(change, value)

    def update_elem(self):
        # Update x, y considering anchors
        x = self.pos().x()
        y = self.pos().y() + self.boundingRect().height() * 0.75

        anchor = self.elem.get("text-anchor", "start")
        if "text-anchor" in self.elem.get("style", ""):
            if "middle" in self.elem.get("style", ""):
                anchor = "middle"
            elif "end" in self.elem.get("style", ""):
                anchor = "end"

        if anchor == "middle":
            x += self.boundingRect().width() / 2
        elif anchor == "end":
            x += self.boundingRect().width()

        self.elem.set("x", str(x))
        self.elem.set("y", str(y))


class SymbolView(QGraphicsView):
    statusMessage = pyqtSignal(str)
    MODE_SELECT = "Select"
    MODE_LINE = "Line"
    MODE_RECT = "Rect"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.symbol_scene = SymbolScene()
        self.setScene(self.symbol_scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)

        self.zoom_factor = 1.2
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        self.filename = None
        self.xml_root = None
        self.svg_items = []
        self.current_mode = self.MODE_SELECT

        # Drawing state
        self.draw_start = None
        self.temp_item = None

    def wheelEvent(self, event):
        modifiers = event.modifiers()
        if modifiers & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        ):
            old_scene_pos = self.mapToScene(event.position().toPoint())

            if event.angleDelta().y() > 0:
                factor = self.zoom_factor
            else:
                factor = 1 / self.zoom_factor

            self.scale(factor, factor)

            new_scene_pos = self.mapToScene(event.position().toPoint())
            delta = new_scene_pos - old_scene_pos
            self.translate(delta.x(), delta.y())
            event.accept()
        else:
            super().wheelEvent(event)

    def _set_mode(self, mode):
        self.current_mode = mode
        if mode == self.MODE_SELECT:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()
        has_shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

        if key == Qt.Key.Key_F:
            self.fitInView(
                self.scene().itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio
            )
        elif key == Qt.Key.Key_L:
            self._set_mode(self.MODE_LINE)
            self.statusMessage.emit("Mode: Line (Shift+R for Rectangle)")
        elif key == Qt.Key.Key_R:
            if has_shift:
                self._set_mode(self.MODE_RECT)
                self.statusMessage.emit("Mode: Rectangle")
            else:
                self.statusMessage.emit("Press Shift+R for Rectangle mode")
        elif key == Qt.Key.Key_T:
            if has_shift:
                self._add_text()
        elif key == Qt.Key.Key_Delete or key == Qt.Key.Key_Backspace:
            self._delete_selected()
        elif key == Qt.Key.Key_Escape:
            self._set_mode(self.MODE_SELECT)
            if self.temp_item:
                self.scene().removeItem(self.temp_item)
                self.temp_item = None
        else:
            super().keyPressEvent(event)

    def _delete_selected(self):
        items = self.scene().selectedItems()
        for item in items:
            if item in self.svg_items:
                self.svg_items.remove(item)
                if hasattr(item, "elem") and item.elem is not None:
                    # Find parent of the element to remove it from XML
                    for parent in self.xml_root.iter():
                        if item.elem in list(parent):
                            parent.remove(item.elem)
                            break
            self.scene().removeItem(item)

    def _add_text(self):
        if self.xml_root is None:
            return
        # Add to XML
        new_elem = ET.SubElement(
            self.xml_root, "text", {"x": "0", "y": "0", "fill": "black"}
        )
        new_elem.text = "New Text"
        # Add to Scene
        item = SvgTextItem(new_elem)
        self.scene().addItem(item)
        self.svg_items.append(item)
        center = self.mapToScene(self.viewport().rect().center())
        # Snap center to grid
        center_x = round(center.x() / 5) * 5
        center_y = round(center.y() / 5) * 5
        item.setPos(center_x, center_y)
        item.setSelected(True)

    def mousePressEvent(self, event):
        pos = self.mapToScene(event.position().toPoint())

        if (
            self.current_mode in [self.MODE_LINE, self.MODE_RECT]
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.draw_start = pos
            if self.current_mode == self.MODE_LINE:
                self.temp_item = QGraphicsLineItem(QLineF(pos, pos))
                self.temp_item.setPen(QPen(Qt.GlobalColor.black, 2))
            else:
                self.temp_item = QGraphicsRectItem(QRectF(pos, pos))
                self.temp_item.setPen(QPen(Qt.GlobalColor.black, 2))
            self.scene().addItem(self.temp_item)
            return

        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            from PyQt6.QtGui import QMouseEvent
            from PyQt6.QtCore import QEvent

            fake_event = QMouseEvent(
                QEvent.Type.MouseButtonPress,
                event.pos(),
                event.globalPosition(),
                Qt.MouseButton.LeftButton,
                event.buttons() | Qt.MouseButton.LeftButton,
                event.modifiers(),
            )
            super().mousePressEvent(fake_event)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = self.mapToScene(event.position().toPoint())
        if self.temp_item and self.draw_start:
            if self.current_mode == self.MODE_LINE:
                self.temp_item.setLine(QLineF(self.draw_start, pos))
            else:
                rect = QRectF(self.draw_start, pos).normalized()
                self.temp_item.setRect(rect)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        pos = self.mapToScene(event.position().toPoint())

        if self.temp_item and self.draw_start:
            self.scene().removeItem(self.temp_item)
            self.temp_item = None

            if self.current_mode == self.MODE_LINE:
                # Snap to grid
                x1 = round(self.draw_start.x() / 10) * 10
                y1 = round(self.draw_start.y() / 10) * 10
                x2 = round(pos.x() / 10) * 10
                y2 = round(pos.y() / 10) * 10

                new_elem = ET.SubElement(
                    self.xml_root,
                    "line",
                    {
                        "x1": str(x1),
                        "y1": str(y1),
                        "x2": str(x2),
                        "y2": str(y2),
                        "stroke": "black",
                        "stroke-width": "2",
                    },
                )
                item = SvgLineItem(new_elem)
            else:
                rect = QRectF(self.draw_start, pos).normalized()
                # Snap to grid
                rx = round(rect.x() / 10) * 10
                ry = round(rect.y() / 10) * 10
                rw = round(rect.width() / 10) * 10
                rh = round(rect.height() / 10) * 10

                new_elem = ET.SubElement(
                    self.xml_root,
                    "rect",
                    {
                        "x": str(rx),
                        "y": str(ry),
                        "width": str(rw),
                        "height": str(rh),
                        "stroke": "black",
                        "stroke-width": "2",
                        "fill": "none",
                    },
                )
                item = SvgRectItem(new_elem)

            self.scene().addItem(item)
            self.svg_items.append(item)
            self.draw_start = None
            self.current_mode = self.MODE_SELECT
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            return

        if event.button() == Qt.MouseButton.MiddleButton:
            from PyQt6.QtGui import QMouseEvent
            from PyQt6.QtCore import QEvent

            fake_event = QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                event.pos(),
                event.globalPosition(),
                Qt.MouseButton.LeftButton,
                event.buttons() & ~Qt.MouseButton.LeftButton,
                event.modifiers(),
            )
            super().mouseReleaseEvent(fake_event)
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            return
        super().mouseReleaseEvent(event)

    def load_symbol(self, filename):
        self.filename = filename

        try:
            tree = ET.parse(filename)
            self.xml_root = tree.getroot()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load SVG: {e}")
            return

        # Parse basic SVG primitives manually
        for elem in self.xml_root.iter():
            tag = elem.tag.split("}")[-1]
            if tag == "rect":
                item = SvgRectItem(elem)
                self.symbol_scene.addItem(item)
                self.svg_items.append(item)
            elif tag == "line":
                item = SvgLineItem(elem)
                self.symbol_scene.addItem(item)
                self.svg_items.append(item)
            elif tag == "circle":
                item = SvgCircleItem(elem)
                self.symbol_scene.addItem(item)
                self.svg_items.append(item)
            elif tag == "text":
                item = SvgTextItem(elem)
                self.symbol_scene.addItem(item)
                self.svg_items.append(item)

    def save_symbol(self, filename=None):
        if not filename:
            filename = self.filename

        if not filename or not self.xml_root:
            return

        # Update XML elements from UI positions
        for item in self.svg_items:
            item.update_elem()

        # Serialize
        xml_bytes = ET.tostring(self.xml_root, encoding="utf-8")
        xmlstr = minidom.parseString(xml_bytes).toprettyxml(indent="  ")
        xmlstr = "\\n".join([line for line in xmlstr.split("\\n") if line.strip()])

        with open(filename, "w") as f:
            f.write(xmlstr)

        self.filename = filename
        print(f"Saved symbol to {filename}")
