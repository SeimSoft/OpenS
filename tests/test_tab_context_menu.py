from unittest.mock import MagicMock
from PyQt6.QtWidgets import QApplication

from opens_suite.main_window import MainWindow


def test_tab_context_menu_contains_requested_actions(qtbot, tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    win = MainWindow(str(project_dir))
    qtbot.addWidget(win)
    win.new_file()

    menu, actions = win._create_tab_context_menu(0)

    assert menu is not None
    assert actions["save"].text() == "Save"
    assert actions["copy_path"].text() == "Copy Path"
    assert actions["close"].text() == "Close"
    assert actions["close_all"].text() == "Close All"
    assert actions["close_others"].text() == "Close Others"


def test_save_tab_saves_clicked_tab_and_restores_current(qtbot, tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    win = MainWindow(str(project_dir))
    qtbot.addWidget(win)
    win.new_file()
    win.new_file()

    win.tabs.setCurrentIndex(0)
    win.save_file = MagicMock()

    win._save_tab(1)

    win.save_file.assert_called_once()
    assert win.tabs.currentIndex() == 0


def test_close_others_and_close_all_helpers(qtbot, tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    win = MainWindow(str(project_dir))
    qtbot.addWidget(win)
    win.new_file()
    win.new_file()
    win.new_file()

    keep_widget = win.tabs.widget(1)
    win._close_other_tabs(1)

    assert win.tabs.count() == 1
    assert win.tabs.widget(0) is keep_widget

    win.new_file()
    win.new_file()
    assert win.tabs.count() == 3

    win._close_all_tabs()

    assert win.tabs.count() == 0


def test_copy_tab_path_copies_to_clipboard(qtbot, tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    win = MainWindow(str(project_dir))
    qtbot.addWidget(win)
    win.new_file()

    file_path = str(tmp_path / "example.svg")
    view = win.tabs.widget(0)
    view.filename = file_path

    win._copy_tab_path(0)

    assert QApplication.clipboard().text() == file_path
