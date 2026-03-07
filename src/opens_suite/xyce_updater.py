import os
import json
import platform
import urllib.request
import zipfile
import shutil
from PyQt6.QtCore import QObject, pyqtSignal, QThread


class XyceUpdateWorker(QThread):
    progressChanged = pyqtSignal(int, str)  # percentage, status_text
    finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, download_url, target_dir):
        super().__init__()
        self.download_url = download_url
        self.target_dir = target_dir

    def run(self):
        try:
            self.progressChanged.emit(0, "Downloading Xyce...")

            # Determine extension
            ext = ".zip" if self.download_url.endswith(".zip") else ".tar.gz"
            temp_file = os.path.join(self.target_dir, f"xyce_update{ext}")

            def report_hook(count, block_size, total_size):
                if total_size > 0:
                    percent = int(count * block_size * 100 / total_size)
                    self.progressChanged.emit(percent, f"Downloading: {percent}%")

            urllib.request.urlretrieve(
                self.download_url, temp_file, reporthook=report_hook
            )

            self.progressChanged.emit(100, "Extracting files...")

            if ext == ".zip":
                with zipfile.ZipFile(temp_file, "r") as zip_ref:
                    zip_ref.extractall(self.target_dir)
            else:
                import tarfile

                with tarfile.open(temp_file, "r:gz") as tar_ref:
                    tar_ref.extractall(self.target_dir)

            os.remove(temp_file)

            # Fix permissions for unix executables
            self.progressChanged.emit(100, "Setting permissions...")
            for root, dirs, files in os.walk(self.target_dir):
                for file in files:
                    # Give execute permissions to binaries
                    if "bin" in root or file.startswith("Xyce"):
                        path = os.path.join(root, file)
                        os.chmod(path, 0o755)

            self.finished.emit(True, "Update installed successfully.")
        except Exception as e:
            self.finished.emit(False, str(e))


class XyceUpdater(QObject):
    updateAvailable = pyqtSignal(dict)  # Emits release info if update is available
    noUpdateAvailable = pyqtSignal()
    errorOccurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xyce")
        self.version_file = os.path.join(self.base_dir, "version_info.json")
        self.API_URL = (
            "https://api.github.com/repos/SeimSoft/xyce-python/releases/latest"
        )

        # Determine platform keyword used in github release assets
        sys_plat = platform.system().lower()
        if sys_plat == "windows":
            self.asset_keyword = "windows"
        elif sys_plat == "darwin":
            # For now, we prefer intel build if architecture is x86_64, else latest
            if platform.machine() == "x86_64":
                self.asset_keyword = "macos-26-intel"
            else:
                self.asset_keyword = "macos"
        else:
            self.asset_keyword = "ubuntu"

    def get_local_info(self):
        """Returns the local version info dict or None if not found."""
        if os.path.exists(self.version_file):
            try:
                with open(self.version_file, "r") as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def save_local_info(self, info):
        """Saves version info locally."""
        os.makedirs(self.base_dir, exist_ok=True)
        try:
            with open(self.version_file, "w") as f:
                json.dump(info, f, indent=4)
        except Exception as e:
            print(f"Failed to save version info: {e}")

    def check_for_updates(self, force=False):
        """Asynchronously (or quickly) checks for updates via GitHub API."""
        import threading

        def _check():
            try:
                import urllib.request
                import urllib.error

                req = urllib.request.Request(
                    self.API_URL, headers={"User-Agent": "OpenS-Updater"}
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    data = json.loads(response.read().decode("utf-8"))

                latest_version = data.get("tag_name", "")

                # Find the right asset
                download_url = None
                asset_size = 0
                for asset in data.get("assets", []):
                    # Pick the first asset matching our platform
                    name = asset.get("name", "").lower()
                    if self.asset_keyword in name and (
                        name.endswith(".zip") or name.endswith(".tar.gz")
                    ):
                        # If there are multiple macos, prefer intel specifically if we asked for it
                        if self.asset_keyword == "macos":
                            # General macos - if it's the intel one, skip it unless we are intel
                            if "intel" in name and platform.machine() != "x86_64":
                                continue
                        download_url = asset.get("browser_download_url")
                        asset_size = asset.get("size", 0)
                        break

                if not download_url:
                    self.errorOccurred.emit(
                        "No compatible Xyce release found for your platform."
                    )
                    return

                # Calculate a pseudo-hash using the tag and asset size
                # (since GitHub releases API doesn't provide commit hashes directly for assets without extra queries)
                latest_hash = f"{latest_version}_{asset_size}"

                local_info = self.get_local_info()

                needs_update = False
                if force or not local_info:
                    needs_update = True
                else:
                    if (
                        local_info.get("version") != latest_version
                        or local_info.get("hash") != latest_hash
                    ):
                        needs_update = True

                if needs_update:
                    self.updateAvailable.emit(
                        {
                            "version": latest_version,
                            "hash": latest_hash,
                            "download_url": download_url,
                        }
                    )
                else:
                    self.noUpdateAvailable.emit()

            except Exception as e:
                self.errorOccurred.emit(f"Failed to check for updates: {e}")

        # Run check in background thread so it doesn't freeze the GUI
        t = threading.Thread(target=_check)
        t.daemon = True
        t.start()
