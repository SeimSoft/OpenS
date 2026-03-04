import os
import sys
import time
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, Qt

# Setup path to find opens_suite
sys.path.append(os.path.join(os.getcwd(), "src"))

from opens_suite.main_window import MainWindow


def take_screenshot():
    app = QApplication(sys.argv)

    # Create MainWindow
    window = MainWindow()
    window.show()

    # Load a test schematic
    test_svg = os.path.abspath("tests/dc_sim.svg")
    if os.path.exists(test_svg):
        print(f"Loading {test_svg}...")
        window.open_file(test_svg)
    else:
        print(f"Error: {test_svg} not found.")
        app.quit()
        return

    # Wait for UI to settle, then trigger simulation
    def start_sim():
        if hasattr(window, "simulate_action"):
            print("Triggering simulation...")
            window.simulate_action.trigger()

            # Check for simulation completion
            def check_sim():
                # XycePlugin sets simulation_process
                if (
                    not hasattr(window, "simulation_process")
                    or window.simulation_process is None
                    or window.simulation_process.state() == 0
                ):  # NotRunning
                    print("Simulation finished. Waiting for results to load...")
                    # Give it 3 more seconds to load results into the UI (rendering waveforms etc)
                    QTimer.singleShot(3000, do_capture)
                else:
                    # Still running, check again soon
                    QTimer.singleShot(500, check_sim)

            # Wait a bit for the process to start before checking
            QTimer.singleShot(1000, check_sim)
        else:
            print("Error: simulate_action not found (check if XycePlugin loaded).")
            app.quit()

    def do_capture():
        # Ensure the directory exists
        screenshot_dir = os.path.abspath("docs/assets/images")
        os.makedirs(screenshot_dir, exist_ok=True)
        screenshot_path = os.path.join(screenshot_dir, "app_screenshot.png")

        # Grab the window
        window.repaint()
        QApplication.processEvents()

        pixmap = window.grab()
        success = pixmap.save(screenshot_path)

        if success:
            print(f"Screenshot saved to {screenshot_path}")
        else:
            print(f"Failed to save screenshot to {screenshot_path}")

        app.quit()

    # Initial delay to let UI load icons etc.
    QTimer.singleShot(2000, start_sim)

    sys.exit(app.exec())


if __name__ == "__main__":
    take_screenshot()
