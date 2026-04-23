# Features

## ai features
- [ ] tim as mcp accessible via ai chat to take actions on the database
  - [ ] could organize TODOs, cleanup data, etc. can do things i would have had
    to do manually through django admin or write a mgmt command for
- [ ] when a user submits a web link, it should be accessed and summarized with
  tags auto-generated from the content
- [ ] when a user submits a web link use semantic search to find similar blocks
  and pages and show them in sidebar

## general usage
- [ ] reminders/notifications? kinda useless without push notifications which
  require a mobile app i think?
  - maybe can use something like Pusher? i still think you need APN details for
    that
  - maybe can use Twilio? though Sam did say recently that you have to jump
    through some hoops to get a phone number now
- [ ] should be able to drag and move block ordering and nestings around
- [ ] ability to select multiple blocks and perform actions on them
  - [ ] delete multiple blocks
  - [ ] move multiple blocks to current day
- [ ] support for [[this syntax of tags]] in blocks
- [ ] spotlight should allow for actions to, like creating a new page
- [x] graph view of blocks/pages (#39) - force-directed canvas at `/knowledge/graph/`,
  built from block→page tag M2M and `[[title]]` wiki links

# Optimizations
- [ ] need to cleanup frontend routes, django templates, and the vue app
- [ ] infinite scroll for ai chat history
- [-] infinite scroll for daily notes

# Cleanup
- [ ] fix ai_chat forms to take UUIDModelChoiceField, then fix frontend

# Questions

- [ ] Filebase storage vs database? filebase storage could
  be more portable and easier to handle media. hm we'd
  still want some form of metadata for the objects. maybe
  a metadata file with the same name or something? how tenable
  to update if the filename is changed? will the filename be changed?
  how often?

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

- [ ] implement sentence-transformer and chromadb
