from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox
from opens_suite.syntax_highlighter import apply_dark_plus_theme

class TextEditorDialog(QDialog):
    def __init__(self, parent=None, initial_text=""):
        super().__init__(parent)
        self.setWindowTitle("Edit Multiline Text")
        self.resize(600, 400)
        
        layout = QVBoxLayout(self)
        
        self.editor = QTextEdit()
        self.editor.setAcceptRichText(False)
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.editor.setPlainText(initial_text)
        apply_dark_plus_theme(self.editor)
        
        layout.addWidget(self.editor)
        
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)
        
    def get_text(self):
        return self.editor.toPlainText()
