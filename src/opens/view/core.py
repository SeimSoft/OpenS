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

from opens.schematic_item import SchematicItem
from opens.wire import Wire, Junction
from opens.commands import (
    InsertItemsCommand,
    RemoveItemsCommand,
    MoveItemsCommand,
    CreateWireCommand,
    TransformItemsCommand,
)
import xml.etree.ElementTree as ET
import os
from opens.netlister import NetlistGenerator
from opens.spice_parser import SpiceRawParser


from opens.view.io import IOMixin
from opens.view.simulation import SimulationMixin
from opens.view.connectivity import ConnectivityMixin
from opens.view.events import EventsMixin
from opens.view.scene import SchematicScene


class SchematicView(
    IOMixin, SimulationMixin, ConnectivityMixin, EventsMixin, QGraphicsView
):
    MODE_SELECT = "Select"
    MODE_WIRE = "Wire"
    MODE_MOVE = "Move"
    MODE_LINE = "Line"
    MODE_COPY = "Copy"
    MODE_PROBE = "Probe"
    MODE_ZOOM_RECT = "ZoomRect"
    WIRE_MODE_FREE = "Free"
    WIRE_MODE_HV = "HV"  # Horizontal then Vertical
    WIRE_MODE_VH = "VH"  # Vertical then Horizontal

    modeChanged = pyqtSignal(str)
    statusMessage = pyqtSignal(str)
    netSignalsPlotRequested = pyqtSignal(str)
    netProbed = pyqtSignal(str)
    simulationFinished = pyqtSignal()
    openSubcircuitRequested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(SchematicScene(self))

        # Performance Optimizations
        import platform

        if platform.system() != "Darwin":
            try:
                from PyQt6.QtOpenGLWidgets import QOpenGLWidget

                self.setViewport(QOpenGLWidget())
            except ImportError:
                print(
                    "Note: PyQt6.QtOpenGLWidgets not found. Hardware acceleration disabled."
                )
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setOptimizationFlags(
            QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing
        )

        # Undo Stack
        self.undo_stack = QUndoStack(self)
        self.undo_stack.indexChanged.connect(self.recalculate_connectivity)

        # Navigation
        self.setDragMode(
            QGraphicsView.DragMode.RubberBandDrag
        )  # Default to rubber band
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        # Zooming
        self.zoom_factor = 1.3

        # Drag and Drop
        self.setAcceptDrops(True)

        # State
        self.current_mode = self.MODE_SELECT
        self.wire_submode = self.WIRE_MODE_FREE
        self.wire_hv_mode = True  # Default Horizontal First
        self.wire_mode_locked = False

        self.wire_start = None
        self.current_wire = None

        # Line Mode
        self.line_start = None
        self.current_line_item = None

        self.wire_preview_path = QGraphicsPathItem()
        self.scene().addItem(self.wire_preview_path)
        self.wire_preview_path.setVisible(False)

        # Zoom Rect Preview
        self.zoom_rect_item = QGraphicsRectItem()
        self.zoom_rect_item.setPen(QPen(QColor(0, 0, 255), 1, Qt.PenStyle.DashLine))
        self.zoom_rect_item.setBrush(QColor(0, 0, 255, 30))
        self.scene().addItem(self.zoom_rect_item)
        self.zoom_rect_item.setVisible(False)
        self.zoom_start_pos = None
        self.move_ref_pos = None
        self.moving_items = []
        self.rubber_band_data = []  # List of (wire, moving_endpoint_index)

        # Copy Mode State
        self.copy_ref_pos = None
        self.copy_source_items = []
        self.copy_preview_items = []

        self.analyses = []
        self.outputs = []
        self.filename = None
        self.last_item_to_node = {}  # item -> node_name from last simulation

        from opens.theme import theme_manager

        self.apply_theme()
        theme_manager.themeChanged.connect(self.apply_theme)

    def _connect_item(self, item):
        if isinstance(item, SchematicItem):
            item.openSubcircuitRequested.connect(self.openSubcircuitRequested.emit)

    def apply_theme(self):
        from opens.theme import theme_manager

        self.wire_preview_path.setPen(
            QPen(theme_manager.get_color("font_label"), 2, Qt.PenStyle.DashLine)
        )
        self.update()

    def reload_symbols(self):
        """Reloads all symbols in the scene from disk."""
        for item in self.scene().items():
            if isinstance(item, SchematicItem):
                item.reload_symbol()
        self.recalculate_connectivity()

    def set_mode(self, mode):
        self.current_mode = mode
        self.modeChanged.emit(mode)

        self.recalculate_connectivity()

        if mode == self.MODE_SELECT:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            # Cancel operations
            self.wire_preview_path.setVisible(False)
            self.wire_start = None
            if self.current_wire:
                self.scene().removeItem(self.current_wire)
                self.current_wire = None

            self.move_ref_pos = None
            self.moving_items = []
            self.rubber_band_data = []

            # Cleanup copy mode
            for item in self.copy_preview_items:
                self.scene().removeItem(item)
            self.copy_preview_items = []
            self.copy_ref_pos = None
            self.copy_source_items = []

            self.statusMessage.emit("Mode: Select")

        elif mode == self.MODE_WIRE:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.statusMessage.emit(f"Mode: Wire")
            self.wire_mode_locked = False

        elif mode == self.MODE_MOVE:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            self.move_ref_pos = None  # Old move ref
            self.move_start = None  # New move start
            # Prepare moving items
            self.moving_items = self.scene().selectedItems()
            self.statusMessage.emit("Mode: Move (Click to pick up)")

        elif mode == self.MODE_COPY:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            self.copy_ref_pos = None
            self.copy_source_items = [
                it for it in self.scene().selectedItems() if it.parentItem() is None
            ]
            # Cleanup previous previews if any
            for item in self.copy_preview_items:
                self.scene().removeItem(item)
            self.copy_preview_items = []
            self.statusMessage.emit("Mode: Copy (Click reference point)")

        elif mode == self.MODE_LINE:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.statusMessage.emit("Mode: Line")
            self.line_start = None
