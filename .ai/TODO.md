# Features

## ai features
- [x] AI chat with database write tools, per-call approval, inline tool traces,
  opt-in auto-approve, and web-search toggle (#6, #43, #44, #45). Read tools
  (search_notes, get_page_by_title, get_block_by_id) and write tools
  (create_block, edit_block, move_blocks, reorder_blocks, create_page).
- [ ] tim as mcp accessible via ai chat to take actions on the database
  - the in-app tool loop covers most of this; the open question is whether to
    expose the same surface as a real MCP server for use by Claude Desktop /
    Claude Code outside the app
- [ ] when a user submits a web link, AI auto-summary + auto-tags from the
  content (#38 phase 4)
  - foundation in place: WebArchive stores extracted_text; capture pipeline
    runs on demand
  - needs an AI pass that inserts TL;DR, key claims, suggested tags as child
    blocks once capture completes
- [ ] when a user submits a web link use semantic search to find similar blocks
  and pages and show them in sidebar (#38 phase 4 "connects to [[existing
  pages]]")

## general usage
- [x] graph view of blocks/pages (#39) — force-directed canvas at
  `/knowledge/graph/`, built from block→page tag M2M and `[[title]]` wiki links
- [x] paste / drag-drop a URL → embed block + opt-in archive of the page
  (#38 phase 1). Readable HTML + raw HTML stored as Assets, archives
  soft-deleted on block delete so the bytes survive for a future library view.
- [x] markdown list paste creates the block hierarchy (#29)
- [x] spotlight commands for new block / new page / new whiteboard, sidebar
  toggles, today, graph, settings, help
- [x] whiteboard feature (#31) — tldraw integrated as a page type
- [ ] reminders/notifications? kinda useless without push notifications which
  require a mobile app i think?
  - maybe can use something like Pusher? i still think you need APN details for
    that
  - maybe can use Twilio? though Sam did say recently that you have to jump
    through some hoops to get a phone number now
- [ ] should be able to drag and move block ordering and nestings around
  (URL drag-drop landed; intra-page block drag-drop is still TODO)
- [ ] ability to select multiple blocks and perform actions on them
  - [ ] delete multiple blocks
  - [ ] move multiple blocks to current day
- [ ] support for [[this syntax of tags]] in blocks (graph view consumes the
  syntax; the editor doesn't extract or render it yet)

# Web archives — phase 2-6 follow-ups (#38)

Phase 1 (capture pipeline, embed block, opt-in archive button, soft-delete on
block delete) shipped. The remaining phases:

- [ ] reader view: dedicated route (not modal) with controlled typography,
  ~65ch width, dark mode, scroll position persistence, select-to-highlight
  → annotation child blocks
- [ ] FTS / vector indexing over `WebArchive.extracted_text` so archives
  participate in search like any other block. `text_sha256` column already
  populated for future dedupe.
- [ ] AI pass at capture: TL;DR, 3-5 key claims as child blocks, suggested
  tags from existing vocabulary, "connects to [[existing pages]]" note,
  open questions surfaced from the article
- [ ] queue / library view for unread + soft-deleted archives + daily digest
  block on the journal ("3 articles in queue relevant to this week's work")
- [ ] durability: "update snapshot" re-fetches and diffs against prior
  capture; POST to Wayback Machine Save Page Now as fallback; paywall
  capture via logged-in browser cookies
- [ ] swap stdlib HTMLParser fallback for trafilatura or readability-lxml
  for higher-quality extraction
- [ ] retry button on failed archives (currently the user has to delete the
  block + re-paste to retry)

# Optimizations
- [ ] need to cleanup frontend routes, django templates, and the vue app
- [ ] infinite scroll for ai chat history
- [-] infinite scroll for daily notes

# Cleanup
- [ ] fix ai_chat forms to take UUIDModelChoiceField, then fix frontend

# Questions

- [x] Filebase storage vs database? Decided to keep Django FileField + local
  MEDIA_ROOT for now (works on a single server, no new infra). When we
  outgrow it (multi-server, CDN, disk pressure) the swap is one settings
  change away via django-storages → S3 / R2 / MinIO / Filebase. Revisit
  then, not before.

# Bugs

- [-] hitting "enter" to create a new block when on a note from a previous day,
  it incorrectly creates a new block for the current day instead of under the
  active block
- [ ] when hitting tab on a new block, it indents the block properly, but it
  does not keep focus on the block
- [ ] can't see nested blocks for past daily notes in list view
  - maybe this isn't the worst ui, but we should show that there are nested
    blocks and either let the user expand them there or let the user click into
    the note. the latter should be possible regardless.
- [ ] it's possible to delete a page. this will delete any direct blocks for the
  page, but will not delete reference blocks. when you click the tag in a ref
  block, it will say failed to load page. in logseq it looks like it recreates
  the page if it doesn't exist, but the previous referenced blocks are no longer
  referenced. should we try to reference existing blocks with tags that match
  new pages?

# Maybe later

- [ ] implement sentence-transformer and chromadb (unblocks #38 phase 4
  "connects to existing pages" + similar-blocks sidebar)
