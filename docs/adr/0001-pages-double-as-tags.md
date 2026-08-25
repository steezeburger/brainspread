# Pages double as tags

There is no separate tag entity. Writing `#groceries` on a block ties that block
to the page named Groceries, so a tag is something you can open, write on, and
reference like any other page.

This was inherited rather than chosen. An agent cloned Logseq's shape in one
shot, it worked, and it stayed. It earns its place now: one vocabulary for
naming things instead of two, and a tag accumulates its own notes over time.

It left two threads behind. "Page" ends up covering both containment and
classification, which CONTEXT.md handles by naming the containing one the
*source page*. And it brought two reference syntaxes with it, `#slug` and
`[[Title]]`, which behave the same today. CONTEXT.md gives them separate jobs
(a *tag* for things you will want to find or act on, a *link* for prose) but
nothing enforces that split yet, and whether it should is still open.
