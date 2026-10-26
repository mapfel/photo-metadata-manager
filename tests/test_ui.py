from metadata_comparer.ui.main_window import MainWindow
from metadata_comparer.ui.thumbnail_view import list_images


def test_list_images_filters_and_sorts(tmp_path):
    for name in ("b.JPG", "a.jpeg", "notes.txt", "c.png"):
        (tmp_path / name).touch()
    (tmp_path / "folder.jpg").mkdir()

    assert [path.name for path in list_images(tmp_path)] == ["a.jpeg", "b.JPG", "c.png"]


def test_selecting_image_fills_metadata_table(qapp, jpeg_file):
    window = MainWindow()
    window._show_folder(jpeg_file.parent)
    assert window.thumbnails.thumbnail_model.rowCount() == 1

    window.thumbnails.setCurrentIndex(window.thumbnails.thumbnail_model.index(0))

    table = window.metadata_table.table_model
    assert table.columnCount() == 5
    assert table.rowCount() == len(window._mappings)
