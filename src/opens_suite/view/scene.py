from PyQt6.QtWidgets import QGraphicsScene
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from opens_suite.theme import theme_manager


class SchematicScene(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid_size = 20
        self._grid_tile = None

        # Set a large enough scene rect
        self.setSceneRect(-5000, -5000, 10000, 10000)

        self.apply_theme()
        theme_manager.themeChanged.connect(self.apply_theme)

    def apply_theme(self):
        self.setBackgroundBrush(theme_manager.get_color("background_schematic"))
        self.grid_color = theme_manager.get_color("grid_dots")
        self._grid_tile = None  # Invalidate cached tile
        self.update()

    def _get_grid_tile(self, painter):
        if self._grid_tile:
            return self._grid_tile

        # Create a single tile for the grid
        tile_size = self.grid_size
        self._grid_tile = QPixmap(tile_size, tile_size)
        self._grid_tile.fill(Qt.GlobalColor.transparent)

        tile_painter = QPainter(self._grid_tile)
        tile_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        tile_painter.setPen(Qt.PenStyle.NoPen)
        tile_painter.setBrush(self.grid_color)

        dot_size = 1.5
        # The dot is at (0,0) in the tile, which corresponds to grid intersections
        tile_painter.drawEllipse(
            QPointF(0, 0), dot_size / 2, dot_size / 2
        )
        tile_painter.end()

        return self._grid_tile

    def drawBackground(self, painter, rect):
        # Fill background
        bg_brush = self.backgroundBrush()
        painter.fillRect(rect, bg_brush)

        # Skip dots if zoomed out too much (roughly < 0.2 scale)
        # We can check the transform of the painter
        transform = painter.transform()
        scale = transform.m11()
        if scale < 0.2:
            return

        # Draw grid points using tiled pixmap for performance
        tile = self._get_grid_tile(painter)
        
        # We need to align the tiling with the grid intersections
        # Since our tile has the dot at (0,0), we just draw it
        painter.drawTiledPixmap(rect, tile, rect.topLeft())
