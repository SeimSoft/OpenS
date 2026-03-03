from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QLineEdit, QLabel
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont


class SimulationLogWidget(QWidget):
    sendInputRequested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)

        font = QFont("monospace")
        if not font.fixedPitch():
            font.setStyleHint(QFont.StyleHint.Monospace)
        self.text_edit.setFont(font)
        layout.addWidget(self.text_edit)

        # Input area
        input_container = QWidget()
        input_layout = QVBoxLayout(input_container)
        input_layout.setContentsMargins(4, 4, 4, 4)
        input_layout.setSpacing(2)

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText(
            "Enter command for simulation (e.g. for pdb)..."
        )
        self.input_edit.returnPressed.connect(self._on_return_pressed)

        # Help label
        self.help_label = QLabel("Press Enter to send to simulation stdin")
        self.help_label.setStyleSheet("font-size: 8pt; color: #777;")

        input_layout.addWidget(self.input_edit)
        input_layout.addWidget(self.help_label)

        layout.addWidget(input_container)

    def _on_return_pressed(self):
        text = self.input_edit.text()
        if text:
            self.sendInputRequested.emit(text + "\n")
            # Clear input and echo to log?
            self.text_edit.append(f"<font color='blue'>> {text}</font>")
            self.input_edit.clear()

    def clear(self):
        self.text_edit.clear()

    def appendText(self, text):
        self.text_edit.insertPlainText(text)
        self.text_edit.ensureCursorVisible()

    def setPlainText(self, text):
        self.text_edit.setPlainText(text)
