from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QLineEdit, QLabel
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFontDatabase


class SimulationLogWidget(QWidget):
    sendInputRequested = pyqtSignal(str)
    copilotAnalysisRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._input_history = []
        self._history_index = None
        self._history_draft = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar for analysis
        import qtawesome as qta
        from PyQt6.QtWidgets import QToolBar, QToolButton
        from PyQt6.QtCore import QSize
        self.toolbar = QToolBar()
        self.toolbar.setIconSize(QSize(16, 16))

        self.copilot_btn = QToolButton()
        self.copilot_btn.setIcon(qta.icon("mdi6.auto-fix", color="#1f1f1f"))
        self.copilot_btn.setText("Ask Copilot for Error Analysis")
        self.copilot_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.copilot_btn.clicked.connect(self.copilotAnalysisRequested.emit)
        self.toolbar.addWidget(self.copilot_btn)

        layout.addWidget(self.toolbar)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)

        self.text_edit.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
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
        self.input_edit.installEventFilter(self)
        self.input_edit.textEdited.connect(self._on_input_edited)

        # Help label
        self.help_label = QLabel("Press Enter to send to simulation stdin")
        self.help_label.setStyleSheet("font-size: 8pt; color: #777;")

        input_layout.addWidget(self.input_edit)
        input_layout.addWidget(self.help_label)

        layout.addWidget(input_container)

    def eventFilter(self, obj, event):
        if obj == self.input_edit and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Up:
                self._history_prev()
                return True
            if event.key() == Qt.Key.Key_Down:
                self._history_next()
                return True
        return super().eventFilter(obj, event)

    def _on_input_edited(self, text):
        if self._history_index is None:
            self._history_draft = text

    def _history_prev(self):
        if not self._input_history:
            return

        if self._history_index is None:
            self._history_draft = self.input_edit.text()
            self._history_index = len(self._input_history) - 1
        else:
            self._history_index = max(0, self._history_index - 1)

        self.input_edit.setText(self._input_history[self._history_index])

    def _history_next(self):
        if self._history_index is None:
            return

        if self._history_index < len(self._input_history) - 1:
            self._history_index += 1
            self.input_edit.setText(self._input_history[self._history_index])
            return

        self._history_index = None
        self.input_edit.setText(self._history_draft)

    def _on_return_pressed(self):
        text = self.input_edit.text()
        if text:
            self._input_history.append(text)
            self._history_index = None
            self._history_draft = ""
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

    def set_ai_features_enabled(self, enabled):
        self.copilot_btn.setVisible(enabled)
        self.copilot_btn.setEnabled(enabled)
        self.toolbar.setVisible(enabled)
