import json
import time

import pytest
from PySide6.QtGui import QImage

from metadata_comparer.config import Config
from metadata_comparer.metadata.cache import CACHE_FILE_NAME, MetadataCache, cached_tags
from metadata_comparer.metadata.mapping import load_mappings
from metadata_comparer.metadata.sources import RawMetadata, Source
from metadata_comparer.metadata.sync import SyncStatus
from metadata_comparer.ui import main_window as main_window_module
from metadata_comparer.ui.main_window import MainWindow
from metadata_comparer.ui.thumbnail_view import IMAGE_SIZE_ROLE, SYNC_ROLE

TAGS = cached_tags(load_mappings())


def wait_for(condition, qapp, timeout=5):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        qapp.processEvents()
    return condition()


def make_jpeg(path, exif_rating=None, xmp_rating=None):
    QImage(8, 8, QImage.Format.Format_RGB32).save(str(path), "JPG")
    if exif_rating is not None or xmp_rating is not None:
        write_ratings(path, exif_rating, xmp_rating)
    return path


def write_ratings(path, exif_rating, xmp_rating):
    exiv2 = pytest.importorskip("exiv2", exc_type=ImportError)
    image = exiv2.ImageFactory.open(str(path))
    image.readMetadata()
    image.exifData()["Exif.Image.Rating"] = str(exif_rating)
    image.xmpData()["Xmp.xmp.Rating"] = str(xmp_rating)
    image.writeMetadata()


def raw(rating="3", title="Ünïcode", sidecar=None):
    return RawMetadata(
        tags={
            Source.XMP_EMBEDDED: {"Xmp.xmp.Rating": [rating], "Xmp.dc.title": [title]},
            Source.EXIF: {"Exif.Image.Rating": [rating], "Exif.Photo.MakerNote": ["blob"]},
        },
        sidecar_path=sidecar,
    )


def test_cache_keeps_only_mapped_tags(tmp_path):
    cache = MetadataCache(tmp_path, TAGS)
    stored = cache.put(tmp_path / "a.jpg", raw())
    assert "Exif.Photo.MakerNote" not in stored.tags[Source.EXIF]
    assert cache.get(tmp_path / "a.jpg").tags[Source.EXIF] == {"Exif.Image.Rating": ["3"]}


def test_cache_round_trips(tmp_path):
    cache = MetadataCache(tmp_path, TAGS)
    cache.put(tmp_path / "a.jpg", raw(sidecar=tmp_path / "a.xmp"))
    cache.put(tmp_path / "b.jpg", raw(rating="5"))
    assert cache.dirty
    cache.save()
    assert not cache.dirty

    loaded = MetadataCache.load(tmp_path, TAGS)
    assert len(loaded) == 2
    assert loaded.get(tmp_path / "a.jpg") == cache.get(tmp_path / "a.jpg")
    assert loaded.get(tmp_path / "a.jpg").sidecar_path == tmp_path / "a.xmp"
    assert loaded.get(tmp_path / "b.jpg").tags[Source.XMP_EMBEDDED]["Xmp.xmp.Rating"] == ["5"]


def test_unreadable_metadata_is_not_cached(tmp_path):
    cache = MetadataCache(tmp_path, TAGS)
    failed = RawMetadata(errors=["exiv2 is not available"])
    assert cache.put(tmp_path / "a.jpg", failed) is failed
    assert cache.get(tmp_path / "a.jpg") is None


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        json.dumps({"version": 999, "tags": sorted(TAGS), "images": {}}),
        json.dumps({"version": 1, "tags": ["Xmp.xmp.Rating"], "images": {"a.jpg": {}}}),
        json.dumps({"version": 1, "tags": sorted(TAGS), "images": {"a.jpg": {"tags": 1}}}),
    ],
)
def test_unusable_cache_file_gives_empty_cache(tmp_path, content):
    (tmp_path / CACHE_FILE_NAME).write_text(content, encoding="utf-8")
    assert len(MetadataCache.load(tmp_path, TAGS)) == 0


def test_keep_only_drops_removed_images(tmp_path):
    cache = MetadataCache(tmp_path, TAGS)
    cache.put(tmp_path / "a.jpg", raw())
    cache.put(tmp_path / "b.jpg", raw())
    cache.save()
    cache.keep_only({"a.jpg"})
    assert cache.dirty
    assert cache.get(tmp_path / "b.jpg") is None


def open_folder(window, folder, qapp, count):
    window._show_folder(folder)
    assert wait_for(lambda: window._cache is not None and len(window._cache) == count, qapp)
    window._save_cache()


def status(window, row, qapp):
    model = window.thumbnails.thumbnail_model
    assert wait_for(lambda: model.data(model.index(row), SYNC_ROLE) is not None, qapp)
    return model.data(model.index(row), SYNC_ROLE).status


def test_new_folder_is_scanned_into_cache_file(qapp, tmp_path):
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        make_jpeg(tmp_path / name)
    window = MainWindow()
    # No thumbnail is displayed, so the scan alone fills the cache.
    open_folder(window, tmp_path, qapp, 3)
    document = json.loads((tmp_path / CACHE_FILE_NAME).read_text(encoding="utf-8"))
    assert set(document["images"]) == {"a.jpg", "b.jpg", "c.jpg"}


def test_cached_folder_is_not_read_again(qapp, tmp_path, monkeypatch):
    image = make_jpeg(tmp_path / "a.jpg", exif_rating=3, xmp_rating=3)
    open_folder(MainWindow(), tmp_path, qapp, 1)

    write_ratings(image, 2, 4)  # another program; the cache does not notice
    reads = []
    real_read = main_window_module.read_metadata
    monkeypatch.setattr(
        main_window_module, "read_metadata", lambda path: reads.append(path) or real_read(path)
    )
    window = MainWindow()
    window._show_folder(tmp_path)
    assert status(window, 0, qapp) == SyncStatus.OK
    window.thumbnails.setCurrentIndex(window.thumbnails.view_index(0))
    assert reads == []  # frame and table both came from the cache

    window.rescan()
    assert wait_for(lambda: status(window, 0, qapp) == SyncStatus.CONFLICT, qapp)
    assert reads


def test_writing_updates_the_cache(qapp, tmp_path):
    image = make_jpeg(tmp_path / "a.jpg", exif_rating=2, xmp_rating=4)
    window = MainWindow()
    open_folder(window, tmp_path, qapp, 1)
    assert status(window, 0, qapp) == SyncStatus.CONFLICT
    window.thumbnails.setCurrentIndex(window.thumbnails.view_index(0))

    panel = window.metadata_panel.model
    rating = [m.name for m in window._mappings].index("Rating")
    panel.click_cell(panel.index(rating, 1))  # embedded XMP is the truth
    panel.toggle_target(panel.index(rating, 0))
    window.metadata_panel.apply()

    cached = window._cache.get(image)
    assert cached.tags[Source.EXIF]["Exif.Image.Rating"] == ["4"]
    assert wait_for(lambda: status(window, 0, qapp) == SyncStatus.OK, qapp)


def test_opening_sync_dialog_rereads_images(qapp, tmp_path, monkeypatch):
    image = make_jpeg(tmp_path / "a.jpg", exif_rating=3, xmp_rating=3)
    window = MainWindow()
    open_folder(window, tmp_path, qapp, 1)
    write_ratings(image, 2, 4)

    monkeypatch.setattr(main_window_module.SyncDialog, "exec", lambda dialog: 0)
    window._open_sync_dialog([image])

    assert window._cache.get(image).tags[Source.EXIF]["Exif.Image.Rating"] == ["2"]
    assert wait_for(lambda: status(window, 0, qapp) == SyncStatus.CONFLICT, qapp)


def test_disabled_cache_writes_nothing(qapp, tmp_path):
    make_jpeg(tmp_path / "a.jpg")
    window = MainWindow(Config(cache_enabled=False))
    assert not window.cache_box.isChecked()
    window._show_folder(tmp_path)
    window.thumbnails.set_status_filter(frozenset({SyncStatus.OK}))  # reads every image
    assert status(window, 0, qapp) is not None
    window._save_cache()
    assert window._cache is None
    assert not (tmp_path / CACHE_FILE_NAME).exists()


def test_cache_checkbox_toggles_and_rebuilds(qapp, tmp_path):
    make_jpeg(tmp_path / "a.jpg")
    window = MainWindow()
    assert window.cache_box.isChecked()  # default on
    window._show_folder(tmp_path)

    window.cache_box.setChecked(False)
    assert window._cache is None
    assert not window._config.cache_enabled

    window.cache_box.setChecked(True)
    assert window._config.cache_enabled
    assert wait_for(lambda: len(window._cache) == 1, qapp)


def test_cache_keeps_image_size(tmp_path):
    cache = MetadataCache(tmp_path, TAGS)
    cache.put(tmp_path / "a.jpg", RawMetadata(tags={}, image_size=(4000, 3000)))
    cache.save()
    assert MetadataCache.load(tmp_path, TAGS).get(tmp_path / "a.jpg").image_size == (4000, 3000)


def test_cache_of_older_version_is_rebuilt(tmp_path):
    document = {
        "version": 1,
        "tags": sorted(TAGS),
        "images": {"a.jpg": {"sidecar": None, "tags": {}}},
    }
    (tmp_path / CACHE_FILE_NAME).write_text(json.dumps(document), encoding="utf-8")
    assert len(MetadataCache.load(tmp_path, TAGS)) == 0


def test_cached_folder_draws_frames_without_reading_files(qapp, tmp_path, monkeypatch):
    make_jpeg(tmp_path / "a.jpg", exif_rating=2, xmp_rating=4)
    open_folder(MainWindow(), tmp_path, qapp, 1)

    monkeypatch.setattr(main_window_module, "read_metadata", lambda path: pytest.fail("read"))
    window = MainWindow()
    window._show_folder(tmp_path)
    model = window.thumbnails.thumbnail_model
    assert status(window, 0, qapp) == SyncStatus.CONFLICT
    assert model.data(model.index(0), IMAGE_SIZE_ROLE) is not None  # frame can be drawn
