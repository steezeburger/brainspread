import hashlib
import logging
import threading
from typing import Callable, Optional

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from common.commands.abstract_base_command import AbstractBaseCommand
from core.models import Asset

from ..forms.capture_url_snapshot_form import CaptureUrlSnapshotForm
from ..models import Block, Snapshot
from ..snapshots import extract_readable, fetch_url

logger = logging.getLogger(__name__)


class CaptureUrlSnapshotCommand(AbstractBaseCommand):
    """
    Create (or reset) a Snapshot row for a block and run the capture pipeline.

    By default the capture runs in a background thread so the API returns
    immediately with the pending row; callers then poll for completion. Tests
    (and any synchronous caller) can pass run_async=False to get the capture
    inline.
    """

    def __init__(
        self,
        form: CaptureUrlSnapshotForm,
        run_async: bool = True,
        fetcher: Optional[Callable] = None,
    ) -> None:
        self.form = form
        self.run_async = run_async
        # Injected so tests can mock network fetches without patching imports.
        self._fetcher = fetcher or fetch_url

    def execute(self) -> Snapshot:
        super().execute()

        user = self.form.cleaned_data["user"]
        block: Block = self.form.cleaned_data["block"]
        url: str = self.form.cleaned_data["url"]

        # Mirror the URL onto the block so render-time lookups don't need a
        # join; keep snapshot row canonical though.
        if block.media_url != url or block.content_type != "embed":
            block.media_url = url
            block.content_type = "embed"
            block.save(update_fields=["media_url", "content_type", "modified_at"])

        snapshot, _ = Snapshot.objects.update_or_create(
            block=block,
            defaults={
                "user": user,
                "source_url": url,
                "status": "pending",
                "failure_reason": "",
            },
        )

        if self.run_async:
            thread = threading.Thread(
                target=_run_capture_threadsafe,
                args=(snapshot.uuid, self._fetcher),
                daemon=True,
            )
            thread.start()
        else:
            _run_capture(snapshot.uuid, fetcher=self._fetcher)
            snapshot.refresh_from_db()

        return snapshot


def _run_capture_threadsafe(snapshot_uuid, fetcher: Callable) -> None:
    """
    Thread entrypoint. Needs its own DB connection (Django opens one per
    thread) and must swallow exceptions - there's no one to log them to
    otherwise.
    """
    from django.db import connection

    try:
        _run_capture(snapshot_uuid, fetcher=fetcher)
    except Exception as exc:  # noqa: BLE001 - last line of defence in worker
        logger.exception("snapshot capture crashed: %s", exc)
    finally:
        connection.close()


def _run_capture(snapshot_uuid, fetcher: Callable) -> None:
    snapshot = Snapshot.objects.filter(uuid=snapshot_uuid).first()
    if snapshot is None:
        return

    Snapshot.objects.filter(pk=snapshot.pk).update(status="in_progress")

    try:
        fetched = fetcher(snapshot.source_url)
    except Exception as exc:  # noqa: BLE001 - any network/HTTP failure
        Snapshot.objects.filter(pk=snapshot.pk).update(
            status="failed",
            failure_reason=f"fetch failed: {exc}"[:2000],
        )
        return

    try:
        extracted = extract_readable(fetched.html, final_url=fetched.final_url)
    except Exception as exc:  # noqa: BLE001 - extractor is best-effort
        Snapshot.objects.filter(pk=snapshot.pk).update(
            status="failed",
            failure_reason=f"extract failed: {exc}"[:2000],
        )
        return

    with transaction.atomic():
        snapshot = Snapshot.objects.select_for_update().get(pk=snapshot.pk)

        readable_asset = _store_asset(
            user=snapshot.user,
            kind="snapshot_readable_html",
            source_url=snapshot.source_url,
            content=extracted.readable_html or "",
            mime_type="text/html; charset=utf-8",
            filename=f"{snapshot.uuid}.readable.html",
        )
        raw_asset = _store_asset(
            user=snapshot.user,
            kind="snapshot_raw_html",
            source_url=snapshot.source_url,
            content=fetched.html,
            mime_type=fetched.content_type or "text/html; charset=utf-8",
            filename=f"{snapshot.uuid}.raw.html",
        )

        text_sha = (
            hashlib.sha256(extracted.plain_text.encode("utf-8")).hexdigest()
            if extracted.plain_text
            else ""
        )

        snapshot.canonical_url = extracted.canonical_url or fetched.final_url
        snapshot.title = extracted.title[:500]
        snapshot.site_name = extracted.site_name[:200]
        snapshot.author = extracted.author[:200]
        snapshot.published_at = extracted.published_at
        snapshot.og_image_url = extracted.og_image_url[:2048]
        snapshot.favicon_url = extracted.favicon_url[:2048]
        snapshot.excerpt = extracted.excerpt
        snapshot.word_count = extracted.word_count
        snapshot.extracted_text = extracted.plain_text
        snapshot.text_sha256 = text_sha
        snapshot.readable_asset = readable_asset
        snapshot.raw_asset = raw_asset
        snapshot.status = "ready"
        snapshot.failure_reason = ""
        snapshot.captured_at = timezone.now()
        snapshot.save()

    # Mirror the extracted title onto the block so the embed renders with
    # real text as soon as capture finishes.
    if extracted.title:
        Block.objects.filter(pk=snapshot.block_id).update(
            content=extracted.title, modified_at=timezone.now()
        )


def _store_asset(
    *,
    user,
    kind: str,
    source_url: str,
    content: str,
    mime_type: str,
    filename: str,
) -> Asset:
    encoded = content.encode("utf-8")
    asset = Asset.objects.create(
        user=user,
        kind=kind,
        source_url=source_url,
        mime_type=mime_type,
        byte_size=len(encoded),
        sha256=hashlib.sha256(encoded).hexdigest(),
    )
    asset.file.save(filename, ContentFile(encoded), save=True)
    return asset
