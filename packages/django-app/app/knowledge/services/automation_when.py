"""Reactive `when::` evaluation (issue #206's "reactive slice").

Schedule due-ness (``automation_schedule.is_due``) only ever asks "does a
slot exist right now" — it has no memory of the automation's *query*
result from one tick to the next. This module adds that memory, in two
independent shapes:

- **Count-baseline edge detection** (``becomes-empty`` /
  ``becomes-nonempty`` / ``count <op> N``): a boolean predicate over the
  matched-block count, edge-detected against the previous run's
  ``result["matched"]`` (the AutomationRun ledger IS the state machine —
  no separate watermark needed). Fires only on the rising edge; every
  other tick's run is recorded SKIPPED so the next tick still has a
  baseline. See :func:`evaluate_count_baseline`.
- **Per-block dwell** (``matched-for <n>m|h|d``): "this block has matched
  continuously for at least this long." Needs a per-block first-matched
  timestamp that survives across ticks — that's what
  ``AutomationBlockMatch`` persists. A block's dwell clock resets the
  moment it drops out of the match set (its row is deleted) or, if
  ``watch::`` names fields/tags to track, the moment one of those changes
  (a changed fingerprint counts as a fresh match). See
  :func:`compute_fingerprint` / :func:`sync_dwell`.

Pure logic module: no DB I/O. The caller (RunAutomationCommand) fetches
the existing dwell rows via AutomationBlockMatchRepository, calls
:func:`sync_dwell`, and persists the result back through the repository.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from .automation_spec import (
    WHEN_BECOMES_EMPTY,
    WHEN_BECOMES_NONEMPTY,
    WHEN_COUNT,
    WHEN_COUNT_OPS,
    WhenSpec,
)

if TYPE_CHECKING:
    from ..models import AutomationBlockMatch, Block


@dataclass(frozen=True)
class WhenOutcome:
    """The verdict for one tick of a count-baseline ``when::`` condition.
    ``reason`` lands in the SKIPPED run's ``result`` for observability —
    see the module docstring for what each reason means."""

    should_fire: bool
    reason: str


def _predicate(when: WhenSpec, matched_count: int) -> bool:
    if when.kind == WHEN_BECOMES_EMPTY:
        return matched_count == 0
    if when.kind == WHEN_BECOMES_NONEMPTY:
        return matched_count > 0
    if when.kind == WHEN_COUNT:
        return WHEN_COUNT_OPS[when.op](matched_count, when.threshold)
    raise ValueError(f"evaluate_count_baseline doesn't handle when.kind={when.kind!r}")


def evaluate_count_baseline(
    when: WhenSpec, matched_count: int, baseline_matched: Optional[int]
) -> WhenOutcome:
    """Edge-detect a ``becomes-empty`` / ``becomes-nonempty`` /
    ``count <op> N`` condition.

    Fires only on the rising edge: the predicate is true for
    ``matched_count`` now and was false for ``baseline_matched`` (the
    prior run's recorded match count, whatever its own outcome). No
    baseline (first run ever, or the prior run recorded none) means
    there's no "before" to transition from — it only establishes one,
    never fires."""
    now_value = _predicate(when, matched_count)
    if baseline_matched is None:
        return WhenOutcome(False, "first-run-empty" if now_value else "first-run")

    was_value = _predicate(when, baseline_matched)
    if now_value and not was_value:
        return WhenOutcome(True, "transitioned")
    if now_value and was_value:
        return WhenOutcome(
            False,
            "still-clear" if when.kind == WHEN_BECOMES_EMPTY else "still-satisfied",
        )
    return WhenOutcome(
        False,
        "still-in-progress" if when.kind == WHEN_BECOMES_EMPTY else "still-unsatisfied",
    )


def compute_fingerprint(block: "Block", watch: Optional[frozenset]) -> dict:
    """A JSON-safe snapshot of the fields/tags a `watch::` prop names, for
    one matched block. Empty (and therefore always equal to itself) when
    `watch::` is unset — dwell then depends only on continuous match-set
    membership, never on a field changing."""
    if not watch:
        return {}
    fingerprint: dict = {}
    for token in watch:
        if token == "due":
            fingerprint["due"] = block.due_at.isoformat() if block.due_at else None
        elif token == "type":
            fingerprint["type"] = block.block_type
        elif token == "content":
            fingerprint["content"] = block.content
        elif token.startswith("tag:"):
            slug = token[len("tag:") :]
            fingerprint[token] = slug in block.get_tag_names()
        elif token.startswith("property:"):
            key = token[len("property:") :]
            fingerprint[token] = (block.properties or {}).get(key)
    return fingerprint


@dataclass(frozen=True)
class DwellSync:
    """The result of syncing one tick's matched blocks against the
    persisted dwell watermarks. ``ready_blocks`` is the subset the
    action should actually run over (dwelled at least ``when.duration``);
    ``upserts``/``stale_block_uuids`` are what the caller persists back
    through AutomationBlockMatchRepository."""

    ready_blocks: List["Block"]
    upserts: List[Tuple[str, datetime, dict]]
    stale_block_uuids: List[str]


def sync_dwell(
    *,
    when: WhenSpec,
    watch: Optional[frozenset],
    blocks: List["Block"],
    existing: Dict[str, "AutomationBlockMatch"],
    now: datetime,
) -> DwellSync:
    """Advance the dwell clock for one tick's matched blocks.

    ``existing`` is every currently-tracked dwell row for this automation,
    keyed by matched block uuid (string) — AutomationBlockMatchRepository
    .get_for_automation()'s shape. A block newly seen, or whose watched
    fingerprint changed since it was first tracked, restarts its clock at
    ``now``; a block that dropped out of ``blocks`` entirely (present in
    ``existing`` but not this tick's matches) is reported in
    ``stale_block_uuids`` so the caller deletes its row — dropping out and
    re-matching later starts the dwell over."""
    matched_uuids = {str(block.uuid) for block in blocks}
    stale_block_uuids = [uuid for uuid in existing if uuid not in matched_uuids]

    ready_blocks: List["Block"] = []
    upserts: List[Tuple[str, datetime, dict]] = []
    for block in blocks:
        block_uuid = str(block.uuid)
        fingerprint = compute_fingerprint(block, watch)
        row = existing.get(block_uuid)
        if row is None or row.fingerprint != fingerprint:
            first_matched_at = now
        else:
            first_matched_at = row.first_matched_at
        upserts.append((block_uuid, first_matched_at, fingerprint))
        if now - first_matched_at >= when.duration:
            ready_blocks.append(block)

    return DwellSync(
        ready_blocks=ready_blocks,
        upserts=upserts,
        stale_block_uuids=stale_block_uuids,
    )
