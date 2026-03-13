import os
import pytest
from PyQt6.QtWidgets import QApplication
from opens_suite.library import LibraryWidget
from unittest.mock import MagicMock, patch


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_create_new_cell_path(qapp, tmp_path):
    # Setup LibraryWidget with a temporary project directory
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    lib_dir = project_dir / "my_lib"
    lib_dir.mkdir()

    widget = LibraryWidget()
    widget.project_dir = str(project_dir)

    # Mock QInputDialog.getText to return a cell name
    with patch("PyQt6.QtWidgets.QInputDialog.getText", return_value=("new_cell", True)):
        # Mock main_window.open_file to avoid opening a real window
        main_window = MagicMock()
        with patch.object(widget, "window", return_value=main_window):
            widget._create_new_cell(str(lib_dir))

    # Check if directory was created
    cell_dir = lib_dir / "new_cell"
    assert cell_dir.exists()
    assert cell_dir.is_dir()

    # Check if schematic.svg was created in the correct location: <lib>/<cell>/schematic.svg
    sch_path = cell_dir / "schematic.svg"
    assert sch_path.exists()
    assert sch_path.is_file()

    # Check if open_file was called with the correct path
    main_window.open_file.assert_called_once_with(str(sch_path))
