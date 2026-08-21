# Pages double as tags

There is no separate tag entity. Writing `#groceries` on a block ties that block
to the page named Groceries, so a tag is something you can open, write on, and
reference like any other page. This follows Logseq's shape: one vocabulary for
naming things instead of two.

The cost is that "page" ends up covering both containment and classification.
CONTEXT.md resolves that by calling the page a block lives on its *source page*,
and reserving *tag* and *link* for the two ways of referencing one.
