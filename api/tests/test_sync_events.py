import asyncio

import pytest

from app.core.errors import ScrapingError
from app.seismic.application.sync_events import SyncSeismicEvents
from app.seismic.infrastructure.ineter_parser import IneterHtmlParser
from tests.fakes import (
    FakeFetcher,
    InMemorySeismicEventRepository,
    NullSyncLock,
    RecordingPublisher,
)


def build_use_case(
    html: str,
    *,
    repository: InMemorySeismicEventRepository | None = None,
    publisher: RecordingPublisher | None = None,
    lock: NullSyncLock | None = None,
) -> tuple[SyncSeismicEvents, InMemorySeismicEventRepository, RecordingPublisher]:
    repo = repository or InMemorySeismicEventRepository()
    pub = publisher or RecordingPublisher()
    use_case = SyncSeismicEvents(
        fetcher=FakeFetcher(html),
        parser=IneterHtmlParser(),
        repository=repo,
        publisher=pub,
        distributed_lock=lock or NullSyncLock(),
    )
    return use_case, repo, pub


@pytest.mark.asyncio
async def test_sync_persists_and_publishes_only_new_events(ineter_html: str) -> None:
    use_case, repository, publisher = build_use_case(ineter_html)

    outcome = await use_case.execute()

    assert outcome is not None
    assert outcome.created == 4
    assert outcome.updated == 0
    assert outcome.scraped == 4
    assert outcome.skipped == 1
    assert await repository.count() == 4
    assert len(publisher.created) == 4
    assert publisher.updated == []


@pytest.mark.asyncio
async def test_second_sync_does_not_duplicate_or_notify(ineter_html: str) -> None:
    use_case, repository, publisher = build_use_case(ineter_html)

    await use_case.execute()
    outcome = await use_case.execute()

    assert outcome is not None
    assert outcome.created == 0
    assert outcome.updated == 0
    assert outcome.unchanged == 4
    assert await repository.count() == 4
    assert len(publisher.created) == 4
    assert publisher.updated == []


@pytest.mark.asyncio
async def test_revised_event_is_updated_not_duplicated(ineter_html: str) -> None:
    fetcher_html = ineter_html
    repository = InMemorySeismicEventRepository()
    publisher = RecordingPublisher()
    fetcher = FakeFetcher(fetcher_html)
    use_case = SyncSeismicEvents(
        fetcher=fetcher,
        parser=IneterHtmlParser(),
        repository=repository,
        publisher=publisher,
        distributed_lock=NullSyncLock(),
    )

    await use_case.execute()
    fetcher.html = ineter_html.replace("3.1", "4.0", 1)
    outcome = await use_case.execute()

    assert outcome is not None
    assert outcome.created == 0
    assert outcome.updated == 1
    assert await repository.count() == 4
    assert len(publisher.updated) == 1
    assert publisher.updated[0].magnitude == 4.0


@pytest.mark.asyncio
async def test_distributed_lock_contention_is_not_an_error(ineter_html: str) -> None:
    use_case, _, publisher = build_use_case(
        ineter_html,
        lock=NullSyncLock(unavailable=True),
    )

    outcome = await use_case.execute()

    assert outcome is None
    assert publisher.created == []


@pytest.mark.asyncio
async def test_zero_event_anchors_raise_scraping_error() -> None:
    use_case, repository, _ = build_use_case("<html><body>maintenance</body></html>")

    with pytest.raises(ScrapingError):
        await use_case.execute()

    assert await repository.count() == 0


@pytest.mark.asyncio
async def test_realtime_failure_does_not_lose_persistence(ineter_html: str) -> None:
    publisher = RecordingPublisher(fail=True)
    use_case, repository, _ = build_use_case(ineter_html, publisher=publisher)

    outcome = await use_case.execute()

    assert outcome is not None
    assert outcome.created == 4
    assert await repository.count() == 4


@pytest.mark.asyncio
async def test_overlapping_runs_are_skipped(ineter_html: str) -> None:
    class BlockingFetcher:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.calls = 0

        async def fetch(self) -> str:
            self.calls += 1
            self.started.set()
            await self.release.wait()
            return ineter_html

    fetcher = BlockingFetcher()
    use_case = SyncSeismicEvents(
        fetcher=fetcher,
        parser=IneterHtmlParser(),
        repository=InMemorySeismicEventRepository(),
        publisher=RecordingPublisher(),
        distributed_lock=NullSyncLock(),
    )

    first = asyncio.create_task(use_case.execute())
    await fetcher.started.wait()
    second = await use_case.execute()
    fetcher.release.set()
    first_outcome = await first

    assert second is None
    assert first_outcome is not None
    assert fetcher.calls == 1
