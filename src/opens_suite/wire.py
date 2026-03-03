from PyQt6.QtWidgets import QGraphicsLineItem, QGraphicsEllipseItem
from PyQt6.QtCore import Qt, QPointF, QLineF
from PyQt6.QtGui import QPen, QColor, QBrush
from opens_suite.theme import theme_manager


class Wire(QGraphicsLineItem):
    def __init__(self, start_pos, end_pos, parent=None):
        super().__init__(start_pos.x(), start_pos.y(), end_pos.x(), end_pos.y(), parent)
        self.setFlag(QGraphicsLineItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsLineItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsLineItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setCacheMode(QGraphicsLineItem.CacheMode.DeviceCoordinateCache)

        self._apply_pen()
        theme_manager.themeChanged.connect(self._apply_pen)

        self.name = None
        self.net_name = None
        self.voltage = None
        self.show_label = True

    def _apply_pen(self):
        self.setPen(
            QPen(
                theme_manager.get_color("line_default"),
                2,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsLineItem.GraphicsItemChange.ItemPositionChange:
            grid_size = 10
            new_pos = value
            x = round(new_pos.x() / grid_size) * grid_size
            y = round(new_pos.y() / grid_size) * grid_size
            return QPointF(x, y)
        return super().itemChange(change, value)

    def boundingRect(self):
        # Extend bounding rect to include potential label shroud
        rect = super().boundingRect()
        return rect.adjusted(-50, -50, 50, 50)

    def paint(self, painter, option, widget=None):
        if self.isSelected():
            painter.setPen(
                QPen(
                    theme_manager.get_color("selection"),
                    2,
                    Qt.PenStyle.DashLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
        else:
            painter.setPen(
                QPen(
                    theme_manager.get_color("line_default"),
                    2,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
        painter.drawLine(self.line())

        # Construct label: Name=Value or just Name or just Value
        label_parts = []
        if self.name:
            label_parts.append(self.name)
        elif self.net_name:
            label_parts.append(self.net_name)

        v_label = None
        if self.voltage is not None:
            v = self.voltage
            if abs(v) >= 1e6:
                v_label = f"{v/1e6:.2f}MegV"
            elif abs(v) >= 1e3:
                v_label = f"{v/1e3:.2f}kV"
            elif abs(v) < 1e-3 and abs(v) > 1e-12:
                v_label = f"{v*1e6:.2f}uV"
            elif abs(v) < 1 and abs(v) > 1e-12:
                v_label = f"{v*1e3:.2f}mV"
            else:
                v_label = f"{v:.2f}V"

        final_label = ""
        if label_parts and v_label:
            final_label = f"{' '.join(label_parts)}={v_label}"
        elif label_parts:
            final_label = " ".join(label_parts)
        elif v_label:
            final_label = v_label

        if final_label and getattr(self, "show_label", True):
            painter.setPen(theme_manager.get_color("font_voltage"))
            font = painter.font()
            font.setPointSize(8)
            painter.setFont(font)

            p1 = self.line().p1()
            p2 = self.line().p2()
            center = (p1 + p2) / 2

            # Use background color for the label shroud to make it readable
            fm = painter.fontMetrics()
            rect = fm.boundingRect(final_label)
            rect.moveCenter(center.toPoint())
            rect = rect.toRectF().adjusted(-2, -1, 2, 1)

            bg = theme_manager.get_color("background_schematic")
            bg.setAlpha(200)
            painter.fillRect(rect, bg)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, final_label)


class Junction(QGraphicsEllipseItem):
    def __init__(self, pos, parent=None):
        radius = 3
        super().__init__(
            pos.x() - radius, pos.y() - radius, radius * 2, radius * 2, parent
        )
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setCacheMode(QGraphicsEllipseItem.CacheMode.DeviceCoordinateCache)
        self.apply_theme()
        theme_manager.themeChanged.connect(self.apply_theme)

    def apply_theme(self):
        self.setBrush(QBrush(theme_manager.get_color("junction")))
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.update()
