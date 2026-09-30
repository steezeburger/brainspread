from datetime import time
from typing import TYPE_CHECKING, List, Optional, TypedDict

from django.conf import settings
from django.db import models

from common.models.crud_timestamps_mixin import CRUDTimestampsMixin
from common.models.soft_delete_timestamp_mixin import SoftDeleteTimestampMixin
from common.models.uuid_mixin import UUIDModelMixin
from knowledge.services.automation_spec import AUTOMATION_TAG_SLUG
from knowledge.services.due_dates import combine_local_to_utc

if TYPE_CHECKING:
    # Page imports Block at module scope, so the reverse import is
    # type-checking only to keep the cycle out of runtime.
    from .page import Page


class Block(UUIDModelMixin, CRUDTimestampsMixin, SoftDeleteTimestampMixin):
    """
    Everything is a block. Blocks can contain text, media, or any other content.
    They can be nested hierarchically and have various types and properties.

    Soft-deleted: block.delete() flips is_active/deleted_at instead of
    removing the row. Deleting/restoring a block cascades to its
    descendant subtree (see BlockRepository.soft_delete_subtree /
    restore_subtree) and archiving/restoring a Page cascades to every
    block on that page (see BlockRepository.soft_delete_page_blocks /
    restore_page_blocks) so blocks on a deleted page disappear from
    block queries even though the block rows themselves aren't touched
    beyond the is_active flag.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="blocks"
    )
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children"
    )
    page = models.ForeignKey("Page", on_delete=models.CASCADE, related_name="blocks")
    pages = models.ManyToManyField(
        "Page",
        related_name="tagged_blocks",
        blank=True,
        help_text="Pages this block belongs to (used for tagging)",
    )

    # Content and media
    content = models.TextField(blank=True, help_text="Text content of the block")
    content_type = models.CharField(
        max_length=20,
        choices=[
            ("text", "Text"),
            ("markdown", "Markdown"),
            ("image", "Image"),
            ("video", "Video"),
            ("audio", "Audio"),
            ("file", "File"),
            ("embed", "Embed"),
            ("code", "Code"),
            ("quote", "Quote"),
        ],
        default="text",
    )

    # For media blocks
    media_url = models.URLField(blank=True, help_text="URL for media content")
    media_file = models.FileField(upload_to="blocks/", blank=True, null=True)
    media_metadata = models.JSONField(
        default=dict, blank=True, help_text="Metadata for media files"
    )
    # First-class asset attachment. Lives alongside media_file during the
    # transition; new code paths (paste / drag-drop / attach) write here,
    # legacy media_file rows can be backfilled later. SET_NULL so deleting
    # the underlying Asset doesn't cascade-delete blocks pointing at it.
    asset = models.ForeignKey(
        "assets.Asset",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blocks",
    )

    # Block properties (key:: value pairs)
    properties = models.JSONField(
        default=dict, blank=True, help_text="Block properties as key-value pairs"
    )

    # Block behavior
    block_type = models.CharField(
        max_length=20,
        choices=[
            ("bullet", "Bullet Point"),
            ("todo", "Todo"),
            ("doing", "Doing"),
            ("done", "Done"),
            ("later", "Later"),
            ("wontdo", "Won't Do"),
            ("heading", "Heading"),
            ("quote", "Quote"),
            ("code", "Code Block"),
            ("divider", "Divider"),
        ],
        default="bullet",
    )

    order = models.PositiveIntegerField(default=0, help_text="Order within parent/page")
    collapsed = models.BooleanField(
        default=False, help_text="Whether block is collapsed"
    )

    # Provenance: which surface wrote this block. Web is the default so
    # pre-existing rows (and test fixtures) read as human-authored;
    # the AI-chat and MCP tool handlers stamp their own value through
    # CreateBlockForm. Clone flows (duplicate page / templates) stamp
    # the surface that performed the clone, not the source block's value.
    CREATED_VIA_WEB = "web"
    CREATED_VIA_AI_CHAT = "ai_chat"
    CREATED_VIA_MCP = "mcp"
    CREATED_VIA_CHOICES = [
        (CREATED_VIA_WEB, "Web"),
        (CREATED_VIA_AI_CHAT, "AI Chat"),
        (CREATED_VIA_MCP, "MCP"),
    ]
    created_via = models.CharField(
        max_length=20,
        choices=CREATED_VIA_CHOICES,
        default=CREATED_VIA_WEB,
        help_text="Which surface created this block (web UI, AI chat, MCP)",
    )

    # Due date/time. Surfaces the block on the matching daily page (see
    # issue #59). All-day by default; due_at_has_time flips on when the
    # user picks a specific time of day. For all-day items the time
    # component is non-meaningful (stored as user-local midnight).
    due_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this block is due (all-day unless due_at_has_time)",
    )
    due_at_has_time = models.BooleanField(
        default=False,
        help_text="True when due_at carries a meaningful time of day",
    )
    # Completion tracking — set when block_type transitions into a terminal
    # state (done/wontdo) and cleared on transition out. modified_at is
    # unreliable for this because it bumps on any edit.
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the block transitioned to a completed state",
    )

    class Meta:
        db_table = "blocks"
        ordering = ("page", "order")
        indexes = [
            models.Index(fields=["user", "page"]),
            models.Index(fields=["parent"]),
            models.Index(fields=["page", "order"]),
            models.Index(fields=["content_type"]),
            models.Index(fields=["block_type"]),
            models.Index(fields=["user", "due_at"]),
            models.Index(fields=["created_via"]),
        ]

    def __str__(self):
        if self.content:
            preview = (
                self.content[:50] + "..." if len(self.content) > 50 else self.content
            )
            return f"Block {self.uuid}: {preview}"
        elif self.media_url or self.media_file:
            return f"Block {self.uuid}: [{self.content_type}]"
        else:
            return f"Block {self.uuid}: [empty]"

    def clean(self) -> None:
        """Normalize the all-day due invariant on validated saves.

        An all-day due (due_at_has_time=False) must sit at user-local
        midnight or _due_local_date() reads back a different calendar day.
        Command write paths guarantee this via services.due_dates.build_due_at;
        direct edits (Django admin runs full_clean) don't — so snap the value
        to midnight of its local date here rather than erroring, preserving
        the editor's intent of "due that local day".
        """
        super().clean()
        if self.due_at and not self.due_at_has_time and self.user_id:
            tz = self.user.tz()
            local = self.due_at.astimezone(tz)
            if local.time() != time.min:
                self.due_at = combine_local_to_utc(local.date(), time.min, tz)

    def get_depth(self):
        """Get the depth/level of this block in the hierarchy"""
        depth = 0
        current = self.parent
        while current:
            depth += 1
            current = current.parent
        return depth

    def get_media_info(self):
        """Get media information for this block"""
        if self.content_type in ["image", "video", "audio", "file"]:
            return {
                "type": self.content_type,
                "url": self.media_url,
                "file": self.media_file.url if self.media_file else None,
                "metadata": self.media_metadata,
            }
        return None

    def first_content_line(self) -> str:
        """First non-empty-safe line of content, or "" for content-less
        blocks. Shared by surfaces that need a title-ish string (reminder
        embeds, automation names) so the empty/whitespace-only edge case
        is handled once."""
        lines = (self.content or "").strip().splitlines()
        return lines[0] if lines else ""

    def get_tags(self) -> list:
        """Pages this block is tagged with, excluding daily notes (a
        daily link means "appears on that daily", not a tag). The
        block's own page is NOT excluded: a block living on a tag page
        it also carries the hashtag for is genuinely tagged with it, and
        hiding that here broke every truth-consumer downstream —
        tag-removal sync could never unlink an own-page tag, and the
        serialized tag list lied to the run-automation menu (issue
        #217). Redundant own-page *display* is a renderer concern, not a
        data one. Filters in Python over ``self.pages.all()`` so a
        ``prefetch_related("pages")`` cache is used instead of bypassed —
        same pattern as get_pending_reminders(). Also drops an archived
        tag page: ``self.pages`` isn't filtered by is_active (only
        BaseRepository.get_queryset() applies that), so an unfiltered
        `.all()` would otherwise leak an archived page back in as a
        chip — the same category of bug as #122's nested-block leak."""
        return [
            page
            for page in self.pages.all()
            if page.is_active and page.page_type != "daily"
        ]

    def get_tag_names(self):
        """Get tag names (uses slug format without # prefix)"""
        return [page.slug for page in self.get_tags()]

    def is_automation(self, tag_slugs: Optional[List[str]] = None) -> bool:
        """Whether this block is a live automation definition. Mirrors
        ``BlockRepository._automation_blocks_qs`` — tagged ``automation``
        or living on the ``automation`` page, never inside a template
        (dormant blueprint) — keep the two in sync. Pass ``tag_slugs``
        when the tag list is already computed (to_dict) to skip
        re-deriving it from get_tags()."""
        if self.page.page_type == "template":
            return False
        slugs = self.get_tag_names() if tag_slugs is None else tag_slugs
        return self.page.slug == AUTOMATION_TAG_SLUG or AUTOMATION_TAG_SLUG in slugs

    def _tag_to_dict(self, tag: "Page") -> "BlockTagData":
        """Serialize one tag page for BlockData["tags"].

        ``name`` is the page slug (what the hashtag chips render). ``uuid``
        / ``title`` / ``page_type`` ride along so surfaces that treat a tag
        as a *page* — the move-to-page picker suggests a block's tag pages
        ahead of the generic recents list — don't need a second round trip
        to resolve the slug back into a page.
        """
        return {
            "name": tag.slug,
            "uuid": str(tag.uuid),
            "title": tag.title,
            "page_type": tag.page_type,
            "color": "#007bff",
        }

    def to_dict(self, include_page_context: bool = False) -> "BlockData":
        """Convert block to dictionary with proper typing"""
        due_date, due_time = self._due_local()
        pending_reminders = self._pending_reminders_local()
        first_reminder = pending_reminders[0] if pending_reminders else None
        tags = self.get_tags()
        data: BlockData = {
            "uuid": str(self.uuid),
            "content": self.content,
            "content_type": self.content_type,
            "block_type": self.block_type,
            "order": self.order,
            "collapsed": self.collapsed,
            "created_via": self.created_via,
            "parent_block_uuid": str(self.parent.uuid) if self.parent else None,
            "page_uuid": str(self.page.uuid),
            "user_uuid": str(self.user.uuid),
            "created_at": self.created_at.isoformat(),
            "modified_at": self.modified_at.isoformat(),
            "media_url": self.media_url,
            "asset": self.asset.to_dict() if self.asset_id else None,
            "properties": self.properties or {},
            "tags": [self._tag_to_dict(tag) for tag in tags],
            # Derived server-side so the client never re-implements the
            # membership rule (tag OR automation-page residency).
            "is_automation": self.is_automation([tag.slug for tag in tags]),
            "children": None,
            # `due_at` is the raw UTC instant; `due_date` / `due_time` are the
            # user-local pieces the UI renders (time is None for all-day items).
            "due_at": (self.due_at.isoformat() if self.due_at else None),
            "due_date": due_date,
            "due_time": due_time,
            "due_at_has_time": self.due_at_has_time,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            # The popover round-trips the full list so a user can re-open
            # it and edit their reminders. Reminder dates may differ from
            # `due_date` — users can be reminded N days before due, etc.
            # The singular fields mirror the earliest pending reminder for
            # compact surfaces (the due-pill badge).
            "pending_reminders": pending_reminders,
            "pending_reminder_date": first_reminder["date"] if first_reminder else None,
            "pending_reminder_time": first_reminder["time"] if first_reminder else None,
            # Page context fields (optional)
            "page_title": None,
            "page_type": None,
            "page_slug": None,
            "page_date": None,
        }

        # Add page context if requested
        if include_page_context and self.page:
            data["page_title"] = self.page.title
            data["page_type"] = self.page.page_type
            data["page_slug"] = self.page.slug
            data["page_date"] = self.page.date.isoformat() if self.page.date else None

        return data

    def _due_local(self) -> "tuple[Optional[str], Optional[str]]":
        """Return the user-local (date, time) of this block's due_at as
        ("YYYY-MM-DD", "HH:MM"). Both None when due_at is unset. The time
        is None for all-day items (due_at_has_time is False) — for those
        due_at is stored at user-local midnight and only the date matters.
        """
        if not self.due_at:
            return (None, None)
        local = self.due_at.astimezone(self.user.tz())
        time_str = local.strftime("%H:%M") if self.due_at_has_time else None
        return (local.strftime("%Y-%m-%d"), time_str)

    def _due_local_time(self) -> Optional[str]:
        return self._due_local()[1]

    def _due_local_date(self) -> Optional[str]:
        return self._due_local()[0]

    def get_pending_reminders(self) -> "list":
        """All pending reminders for this block, earliest fire_at first.

        A block can carry 0..N pending reminders — ScheduleBlockCommand
        replaces the whole pending set on every save. Pending = sent_at IS
        NULL; once a reminder fires (or is cancelled / skipped) sent_at
        gets set. Filters in Python over ``self.reminders.all()`` so a
        ``prefetch_related("reminders")`` cache is used instead of bypassed
        (``.filter()`` on the related manager would issue a fresh query
        per block)."""
        return [r for r in self.reminders.all() if r.sent_at is None]

    def get_pending_reminder(self):
        """Earliest pending reminder, or None. Kept for single-reminder
        surfaces (snooze/cancel tool results, the due-pill badge)."""
        pending = self.get_pending_reminders()
        return pending[0] if pending else None

    def _pending_reminders_local(self) -> "list[PendingReminderData]":
        """User-local ``[{uuid, date, time}, …]`` for every pending
        reminder, earliest first. Drives the popover's editable reminder
        list; date/time are "YYYY-MM-DD" / "HH:MM" strings."""
        tz = self.user.tz()
        out: list[PendingReminderData] = []
        for reminder in self.get_pending_reminders():
            local = reminder.fire_at.astimezone(tz)
            out.append(
                {
                    "uuid": str(reminder.uuid),
                    "date": local.strftime("%Y-%m-%d"),
                    "time": local.strftime("%H:%M"),
                }
            )
        return out

    def as_summary(self) -> "BlockSummaryData":
        """Compact summary for list-shaped tool results (overdue list,
        scheduled list, etc). Smaller than to_dict() — drops media,
        properties, tags, and parent — but rich enough that the chat
        surface can render the row without a follow-up fetch.
        """
        due_date, due_time = self._due_local()
        pending_reminders = self._pending_reminders_local()
        first_reminder = pending_reminders[0] if pending_reminders else None
        return {
            "block_uuid": str(self.uuid),
            "content": self.content,
            "block_type": self.block_type,
            "due_at": (self.due_at.isoformat() if self.due_at else None),
            "due_date": due_date,
            "due_time": due_time,
            "due_at_has_time": self.due_at_has_time,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "page_uuid": str(self.page.uuid) if self.page else None,
            "page_title": self.page.title if self.page else None,
            "page_slug": self.page.slug if self.page else None,
            "pending_reminders": pending_reminders,
            "pending_reminder_date": first_reminder["date"] if first_reminder else None,
            "pending_reminder_time": first_reminder["time"] if first_reminder else None,
        }


class BlockTagData(TypedDict):
    """One tag page attached to a block, as rendered by the hashtag chips
    and consumed by the move-to-page picker's suggestions."""

    name: str
    uuid: str
    title: str
    page_type: str
    color: str


class PendingReminderData(TypedDict):
    """One pending reminder in user-local terms, as round-tripped by the
    schedule popover's editable reminder list."""

    uuid: str
    date: str
    time: str


class BlockSummaryData(TypedDict):
    """Compact subset of BlockData returned by Block.as_summary().

    Used by chat tool_result lists where many blocks ride in a single
    payload — the model doesn't need media / properties / parent ref to
    decide what to do next."""

    block_uuid: str
    content: str
    block_type: str
    due_at: Optional[str]
    due_date: Optional[str]
    due_time: Optional[str]
    due_at_has_time: bool
    completed_at: Optional[str]
    page_uuid: Optional[str]
    page_title: Optional[str]
    page_slug: Optional[str]
    pending_reminders: list[PendingReminderData]
    pending_reminder_date: Optional[str]
    pending_reminder_time: Optional[str]


# API response type for Block data
class BlockData(TypedDict):
    uuid: str
    content: str
    content_type: str
    block_type: str
    order: int
    collapsed: bool
    created_via: str
    parent_block_uuid: Optional[str]
    page_uuid: str
    user_uuid: str
    created_at: str
    modified_at: str
    media_url: str
    asset: Optional[dict]
    properties: dict
    tags: Optional[list[BlockTagData]]
    is_automation: bool
    children: Optional[list["BlockData"]]
    due_at: Optional[str]
    due_date: Optional[str]
    due_time: Optional[str]
    due_at_has_time: bool
    completed_at: Optional[str]
    pending_reminders: list[PendingReminderData]
    pending_reminder_date: Optional[str]
    pending_reminder_time: Optional[str]
    # Page context fields (when included in API responses)
    page_title: Optional[str]
    page_type: Optional[str]
    page_slug: Optional[str]
    page_date: Optional[str]
