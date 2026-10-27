from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from acfv.feedback import FeedbackService
from acfv.library import LibraryService


def test_sqlite_supports_concurrent_product_readers_and_feedback_writers(tmp_path) -> None:
    library = LibraryService(tmp_path / "concurrent.db")
    creator = library.create_creator("Concurrent Creator")
    feedback = FeedbackService(library.repository)
    workers = 8
    barrier = Barrier(workers)

    def exercise(worker: int) -> int:
        barrier.wait(timeout=5)
        written = 0
        for index in range(15):
            if (worker + index) % 3 == 0:
                assert library.list_creators()[0].id == creator.id
                feedback.list_preferences(creator.id)
            else:
                feedback.add_preference(f"prefer topic {worker}-{index}", creator_id=creator.id)
                written += 1
        return written

    with ThreadPoolExecutor(max_workers=workers) as executor:
        expected = sum(executor.map(exercise, range(workers)))

    reopened = LibraryService(tmp_path / "concurrent.db")
    assert len(FeedbackService(reopened.repository).list_preferences(creator.id)) == expected
