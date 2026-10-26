import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths
from PySide6.QtWidgets import QApplication, QMessageBox

from metadata_comparer.config import Config, ConfigError, load_config, write_default_config
from metadata_comparer.metadata.mapping import load_mappings
from metadata_comparer.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("metadata-comparer")
    app.setApplicationDisplayName("Metadata Comparer")

    mappings = load_mappings()
    config_path = _config_path()
    try:
        if not config_path.exists():
            write_default_config(config_path)
        config = load_config(config_path, {mapping.name for mapping in mappings})
    except (OSError, ConfigError) as error:
        QMessageBox.warning(None, "Configuration", f"{error}\n\nUsing the default settings.")
        config = Config()

    # UI state (e.g. the last folder) lives next to config.json, as an INI file.
    settings = QSettings(str(config_path.with_name("state.ini")), QSettings.Format.IniFormat)
    window = MainWindow(config, mappings, settings)
    window.resize(1400, 900)
    window.show()
    window.statusBar().showMessage(f"Configuration: {config_path}")
    return app.exec()


def _config_path() -> Path:
    # e.g. ~/.config/metadata-comparer on Linux, %LOCALAPPDATA%\metadata-comparer on Windows.
    folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    return Path(folder) / "config.json"
