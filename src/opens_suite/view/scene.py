from PyQt6.QtWidgets import QGraphicsScene
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QColor, QPainter, QPen
from opens_suite.theme import theme_manager


class SchematicScene(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid_size = 20

        # Set a large enough scene rect
        self.setSceneRect(-5000, -5000, 10000, 10000)

        self.apply_theme()
        theme_manager.themeChanged.connect(self.apply_theme)

    def apply_theme(self):
        self.setBackgroundBrush(theme_manager.get_color("background_schematic"))
        self.grid_color = theme_manager.get_color("grid_dots")
        self.update()

    def drawBackground(self, painter, rect):
        # Fill background
        bg_brush = self.backgroundBrush()
        painter.fillRect(rect, bg_brush)

        # Draw grid points
        left = int(rect.left()) - (int(rect.left()) % self.grid_size)
        top = int(rect.top()) - (int(rect.top()) % self.grid_size)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.grid_color)

        # Use a small fixed size for dots so they are visible but not too dominant
        dot_size = 1.5

        for x in range(left, int(rect.right()) + self.grid_size, self.grid_size):
            for y in range(top, int(rect.bottom()) + self.grid_size, self.grid_size):
                painter.drawEllipse(QPointF(x, y), dot_size / 2, dot_size / 2)
