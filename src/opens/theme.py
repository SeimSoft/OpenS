from PyQt6.QtGui import QColor
from PyQt6.QtCore import QSettings, pyqtSignal, QObject


class ThemeManager(QObject):
    themeChanged = pyqtSignal()

    BRIGHT_THEME = {
        "background_schematic": "#FFFFFF",
        "grid_dots": "#0000FF",
        "line_default": "#000000",
        "line_mode": "#333333",
        "font_label": "#0000FF",
        "font_voltage": "#0000FF",
        "font_default": "#000000",
        "junction": "#000000",
        "selection": "#FF0000",
    }

    DARK_THEME = {
        "background_schematic": "#000000",
        "grid_dots": "#8C8CA6",  # 140 140 166
        "line_default": "#00CC66",  # Yellow like Virtuoso wires
        "line_mode": "#38BEFE",
        "font_label": "#D8CC00",  # Cyan like Virtuoso
        "font_voltage": "#00FF00",  # Green
        "font_default": "#FFFFFF",
        "junction": "#00CC66",  # cadence: 0 204 102
        "selection": "#FFFFFF",
    }

    def __init__(self):
        super().__init__()
        self.settings = QSettings("OpenS", "OpenS")
        self._load_theme()

    def _load_theme(self):
        # Default to Bright Theme
        self.colors = self.BRIGHT_THEME.copy()
        for key in self.colors.keys():
            val = self.settings.value(f"color/{key}")
            if val:
                self.colors[key] = val

    def get_color(self, key):
        return QColor(self.colors.get(key, "#000000"))

    def set_color(self, key, value):
        if isinstance(value, QColor):
            value = value.name()
        self.colors[key] = value
        self.settings.setValue(f"color/{key}", value)
        self.themeChanged.emit()

    def apply_preset(self, preset_dict):
        for key, val in preset_dict.items():
            self.colors[key] = val
            self.settings.setValue(f"color/{key}", val)
        self.themeChanged.emit()


# Global instance
theme_manager = ThemeManager()
