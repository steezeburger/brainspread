# Brainspread

Note-taking app I built for myself. Big influences: Logseq (daily pages,
everything is an outline) and zettelkasten (tags do the organizing). There's
an MCP server so Claude Code can read and write your notes.

![Brainspread screenshot](docs/images/screenshot2.png)

## Goals

- as little friction as possible when writing something down and keeping it
  organized
- powerful sorting and filtering of tags
- something that keeps me on track, and can nudge me if I ask it to
- a way to loop forgotten things back into my life instead of letting them
  rot below the fold
- automate the stuff I do repeatedly, like:
  - copy my workout to the daily page on Tuesday and Thursday
  - estimate calories and macros whenever a new block tagged `#food-log` is
    created
  - write up new recipes and generate grocery lists from past grocery lists
    and whatever I'm planning to cook
  - sweep everything tagged `#recipe` onto the recipes page once a week

## How it works

The app opens to today's daily page and most notes start there. You can
write on any page directly. The daily just means you never have to figure
out where a note should go before writing it.

A tag is a page and a page is a tag. Typing `#strength-training` in a block
puts that block on the strength-training page. Blocks can be on as many
pages as you tag them with. I'll often dump a bunch of notes under one
tagged block on the daily and move them to their real page later. The plan
is for automations to handle that sorting eventually (by tag, `key:: value`,
whatever).

There's also `[[wiki link]]` syntax with backlinks. I never use it.

## Automations (in progress)

The part I'm most excited about
([#143](https://github.com/steezeburger/brainspread/issues/143)). An
automation is a block tagged `#automation` with
`trigger:: / query:: / action::` properties. The examples under goals are
all this feature. More:

- roll sticky todos onto today every morning
- ping Discord every 15 minutes while a block is `doing` ("still on this?")
- apply the morning routine template on a schedule
- resurface stale stuff I've forgotten about

Automations are ordinary blocks, so a template containing one is basically
an installable automation pack. There's also a sketch for declarative
widgets (habit heatmaps, streaks, countdowns) in
[#168](https://github.com/steezeburger/brainspread/issues/168). The engine
is partially built and landing in slices.

## What's in it

### Blocks and pages

Everything is a block in a nested outline: bullets, todos
(`todo` / `doing` / `done` / `later` / `wontdo`), headings, quotes, code,
images, files. Daily pages are created automatically and old ones stick
around, so it works as a journal too.

### Scheduling and reminders

Scheduling gives a block a due date without moving it. It shows up on that
day's daily page. Overdue stuff collects in the built-in Overdue view, and
undone todos can be rolled forward onto today.

Reminders post to Discord through a webhook, with a mention so it hits your
phone. The message has action links (mark done, mark doing, move to today,
snooze 15m/30m/1h/1d) so you can deal with it from the notification.

### Saved views

Queries over your blocks: block type, tags, due/completed dates,
`key:: value` properties, content, combined with and/or/not. Pin them to the
sidebar or embed them on a page. Embeds can also follow "the daily page", so
a due-today embed shows up on whichever day you have open. Overdue and Done
this week come built in.

Blocks parse `key:: value` lines into queryable properties
(`project:: roadmap`, `priority:: p1`, whatever you invent).

### Templates

A template's block tree can be stamped onto any page. Copies are
independent, so checking off a cloned todo doesn't touch the template. Tags
and embedded views copy over too. My morning routine template brings its
checklist and an open-todos embed with it.

### MCP server

The app works fine with zero AI. That said, there's an MCP server at
`/api/mcp/` (streamable HTTP), and pointing Claude Code at it is really
useful because the agent gets the same primitives the app is built on: due
dates, tags, properties, views, templates, reminders.

- "reschedule everything overdue, spread it over the next week"
- "sweep the recipe blocks scattered across my dailies onto the recipes
  page"
- "put priority:: p1 on the deploy todos and pin a view of open p1s"
- "apply my packing template to today and set a reminder for 7am"

Connect the server to a Claude Code remote session and it's reachable from
the Claude mobile/desktop/web apps, including voice. I use that for
hands-free capture ("remind me to flip the laundry in 30 minutes"), asking
what I was doing when I sit back down, and formatting. One time I pasted an
html table as plain text and asked for a block, and it made a csv table
because brainspread renders those nicely. Once automations land you'll be
able to create one by voice.

16 tools: pages, blocks, todos, search, scheduling, tagging. Each is a thin
wrapper over the same commands the UI uses. Auth is the token you get when
you log in (visible in the Django admin under Auth Tokens):

```bash
claude mcp add --transport http brainspread http://localhost:8001/api/mcp/ \
  --header "Authorization: Token YOUR_TOKEN"
```

### Chat

There's a chat panel in the app too: persistent history, bring your own
keys for Anthropic/OpenAI/Google, web search, approval gate on writes. Good
for quick questions without leaving the app.

### Other stuff

Whiteboards (tldraw), web archives (saves a readable copy of a link on the
block that mentions it), public share links for pages, favorites, graph
view, file attachments, Cmd+K search.

## Quick start

Prerequisites: [Docker](https://docs.docker.com/get-docker/) and
[Just](https://github.com/casey/just).

```bash
cd packages/django-app

just copy-env               # create .env from the template
just generate-secret-key    # paste the output into DJANGO_SECRET_KEY in .env

just create-volumes
just build
just up-d db
just migrate
just reload-db              # loads dev fixtures (admin user)
just up                     # start the app
```

Then open:

- App: http://localhost:8001/
- Admin: http://localhost:8001/admin/
- Login: `admin@email.com` / `password`

For Discord reminders, set your webhook URL and Discord user ID in user
settings and run with `REMINDERS_ENABLED=true`. The scheduler checks for due
reminders every minute.

See [`.ai/PROJECT_SETUP.md`](.ai/PROJECT_SETUP.md) for the full setup
walkthrough.

## Architecture

Django + PostgreSQL, vanilla JavaScript frontend, Docker Compose. Business
logic lives in commands, data access in repositories. See
[`CLAUDE.md`](CLAUDE.md) for the conventions.

## Development

Common tasks (run from `packages/django-app/`):

- `just up` / `just up-d` - start all services (foreground / detached)
- `just down` - stop all services
- `just migrate` / `just makemigrations` - database migrations
- `just shell` - Django shell
- `just test` - run the test suite
- `just reload-db` - reset the database and reload dev fixtures
- `just tail-logs web 100` - tail the last 100 lines of web logs
- `just prepush` - run the pre-push checks (run this before pushing)
