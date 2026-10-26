import sys

from PySide6.QtWidgets import QApplication

from metadata_comparer.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Metadata Comparer")
    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    return app.exec()
