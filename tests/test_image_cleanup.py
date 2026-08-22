from bandi_cards.models import ImageCleanup
import firefly.image_cleanup as cleanup


def test_cleanup_deletes_asset_and_queue_row(web_db, monkeypatch):
    with web_db() as db:
        item = ImageCleanup(image_key="cards/old.webp")
        db.add(item)
        db.commit()
        item_id = item.id

    deleted = []
    monkeypatch.setattr(cleanup, "SessionLocal", web_db)
    monkeypatch.setattr(cleanup.asset_store, "delete", deleted.append)

    assert cleanup.process_image_cleanup_batch() == 1
    assert deleted == ["cards/old.webp"]
    with web_db() as db:
        assert db.get(ImageCleanup, item_id) is None


def test_cleanup_failure_is_retried(web_db, monkeypatch):
    with web_db() as db:
        item = ImageCleanup(image_key="cards/old.webp")
        db.add(item)
        db.commit()
        item_id = item.id

    def fail(_key):
        raise OSError("storage offline")

    monkeypatch.setattr(cleanup, "SessionLocal", web_db)
    monkeypatch.setattr(cleanup.asset_store, "delete", fail)

    assert cleanup.process_image_cleanup_batch() == 0
    with web_db() as db:
        item = db.get(ImageCleanup, item_id)
        assert item.attempts == 1
        assert "storage offline" in item.last_error
