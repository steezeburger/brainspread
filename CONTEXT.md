# Brainspread

Brainspread is an outliner-shaped knowledge tool. Everything a user writes is a
block, blocks live on pages, and pages double as the vocabulary that blocks are
tagged with — there is no separate tag entity.

## Language

**Block**:
The atomic unit of content. Blocks nest inside other blocks to form an outline.
_Avoid_: node, item, bullet (a bullet is one kind of block, not the general term)

**Page**:
A named container for blocks, and the thing a reference points at.
_Avoid_: note, document, file

**Source page**:
The single page a block lives on, as distinct from any pages it references.
_Avoid_: home page, owning page, parent page (_parent_ means the enclosing
**block**, never the page)

**Property**:
A `key:: value` pair carried by a block. Most are typed into the block's own
text, though a few are set by the interface instead.
_Avoid_: attribute, field, metadata

**Asset**:
A stored file owned by a user, whatever produced it. Its *file type* is its
shape (image, pdf, html); its *asset type* is which part of the app made it.
_Avoid_: upload, attachment, media

**Embed**:
A block whose content is an external link, shown as a preview card. Unrelated
to an *embedded view*, despite the shared word.
_Avoid_: card, preview, link block

### References

**Reference**:
A pointer from a block to a page. Written as either a tag or a link.
_Avoid_: mention, citation

**Tag**:
A reference written `#slug`, classifying the block. Tags are what automations
and saved views select on, so reach for one when the block is something you
will want to find or act on later.
_Avoid_: label, category, keyword

**Link**:
A reference written `[[Title]]`, naming a page inside prose. Reach for one when
the page name is simply part of the sentence.
_Avoid_: wiki-link, mention

**Backlink**:
An inbound reference to a page. A page's backlinks are every block that tags it
plus every block that links it, taken together.
_Avoid_: reverse link, inbound link

### Work

**Todo**:
A block whose kind tracks a piece of work: `todo`, `doing`, `later`, `done`, or
`wontdo`. A block is a todo or a heading, never both.
_Avoid_: task, action item, ticket

**Open**:
A todo still in the queue: `todo`, `doing`, or `later`.
_Avoid_: active, pending, outstanding

**Later**:
An open todo the user has parked. It carries no due date - _later_ is about
intent, never about time.
_Avoid_: deferred, snoozed, someday

**Completed**:
A todo that has reached `done` or `wontdo`. Both mean the work has left the
queue, whether or not it got done.
_Avoid_: closed, resolved, archived

**Scheduled**:
Carrying a due date. Orthogonal to whether the todo is open - parking a todo as
_later_ neither sets nor clears its due date.
_Avoid_: planned, dated, due (as a noun)

**Overdue**:
Scheduled for a day that has passed, and still open.
_Avoid_: late, missed, expired

**Reminder**:
A ping about a block at a chosen time. A due date decides where a block
surfaces; a reminder decides when the user hears about it.
_Avoid_: notification, alert, nudge

### Daily notes

**Daily note**:
The page belonging to one calendar day, in the user's own timezone.
_Avoid_: journal, today page, log

**Rollover**:
Moving a user's open todos onto the current daily note. The todo moves rather
than copies, so it leaves the day it was written on.
_Avoid_: carry-over, migration, roll-forward

### Automation

**Automation**:
A rule the user writes as an `#automation` block, pairing a trigger with an
action to run over matching blocks, optionally gated by a condition. The
block is the definition; nothing else records it.
_Avoid_: rule, job, workflow

**Automation run**:
One execution of an automation, recording what fired it and what it did.
_Avoid_: job, invocation, execution

**Condition**:
A `when::` prop that gates whether a trigger's evaluation is worth acting on
— a transition in the query result, a crossed count, or a block's own dwell
time — as opposed to the trigger, which only decides *when* an evaluation
happens. See ADR-0002.
_Avoid_: filter, rule, guard

### Views

**Saved view**:
A named query over the user's blocks. System views ship with the app and can be
cloned but not edited.
_Avoid_: filter, smart list, query

**Template**:
A page whose block tree gets copied onto another page. The copy is independent,
so working through it leaves the template untouched.
_Avoid_: boilerplate, preset, skeleton

**Embedded view**:
A saved view pinned onto a page so its results render there. A *daily*-scoped
one follows the user onto whichever daily note is open rather than sticking to
one date.
_Avoid_: widget, query block, embed

**Whiteboard**:
A page whose body is a drawing canvas instead of blocks.
_Avoid_: canvas, board, sketch

**Graph**:
The network of pages joined by the references between them. Pages are the nodes.
_Avoid_: knowledge graph, network, web

### Assistant

**Chat session**:
One conversation between the user and the assistant.
_Avoid_: thread, conversation, chat

**Pending tool approval**:
A chat turn parked mid-flight because the assistant asked to write something and
needs the user to say yes first.
_Avoid_: confirmation, prompt, gate
