from io import StringIO

import pytest
from django.core.management import call_command

from knowledge.models import Block, Page
from knowledge.test.helpers import BlockFactory, PageFactory, UserFactory


@pytest.fixture
def user(db):
    return UserFactory()


@pytest.fixture
def other_user(db):
    return UserFactory()


def _run(*args):
    out = StringIO()
    call_command("fix_page_slugs", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_reports_no_mismatches_when_everything_matches(user):
    PageFactory(user=user, title="Python", slug="python")
    output = _run()
    assert "No slug/title mismatches found." in output


@pytest.mark.django_db
def test_dry_run_reports_but_does_not_change_slug(user):
    page = PageFactory(user=user, title="Roam Research", slug="roam")
    output = _run()
    assert "roam-research" in output
    assert "Dry-run only" in output
    page.refresh_from_db()
    assert page.slug == "roam"


@pytest.mark.django_db
def test_fix_renames_slug_to_slugified_title(user):
    page = PageFactory(user=user, title="Roam Research", slug="roam")
    _run("--fix")
    page.refresh_from_db()
    assert page.slug == "roam-research"


@pytest.mark.django_db
def test_fix_rewrites_hashtag_references_in_blocks(user):
    target = PageFactory(user=user, title="Repository Pattern", slug="repositories")
    owning_page = PageFactory(user=user, title="Django", slug="django")
    block = BlockFactory(
        user=user,
        page=owning_page,
        content="Use #repositories consistently — see #repositories docs.",
    )
    _run("--fix")
    target.refresh_from_db()
    block.refresh_from_db()
    assert target.slug == "repository-pattern"
    assert "#repository-pattern" in block.content
    assert "#repositories" not in block.content


@pytest.mark.django_db
def test_collisions_are_reported_and_skipped(user):
    # Existing page owns the slug that the drifted page would rename to.
    PageFactory(user=user, title="Roam Research", slug="roam-research")
    drifted = PageFactory(user=user, title="Roam Research", slug="roam")
    output = _run("--fix")
    assert "[COLLISION]" in output
    drifted.refresh_from_db()
    # Skipped — slug unchanged.
    assert drifted.slug == "roam"


@pytest.mark.django_db
def test_scopes_to_single_user_when_email_given(user, other_user):
    mine = PageFactory(user=user, title="Roam Research", slug="roam")
    theirs = PageFactory(user=other_user, title="Roam Research", slug="roam")
    _run("--fix", "--user", user.email)
    mine.refresh_from_db()
    theirs.refresh_from_db()
    assert mine.slug == "roam-research"
    assert theirs.slug == "roam"


@pytest.mark.django_db
def test_ignores_other_users_blocks_when_rewriting_references(user, other_user):
    # Drift on user's page.
    PageFactory(user=user, title="Roam Research", slug="roam")
    # Another user has a block referencing #roam — must not be touched,
    # since that hashtag belongs to *their* roam page (if any) or just
    # plain text in their notes.
    other_page = PageFactory(user=other_user, title="Other", slug="other")
    other_block = BlockFactory(
        user=other_user, page=other_page, content="mentions #roam somewhere"
    )
    _run("--fix")
    other_block.refresh_from_db()
    assert other_block.content == "mentions #roam somewhere"


@pytest.mark.django_db
def test_skips_pages_whose_title_slugifies_to_empty(user):
    # Title made entirely of characters slugify strips — skip it, don't crash.
    page = PageFactory(user=user, title="!!!", slug="odd")
    _run("--fix")
    page.refresh_from_db()
    assert page.slug == "odd"
    # And no stray empty-slug pages got created.
    assert not Page.objects.filter(slug="").exists()


@pytest.mark.django_db
def test_leaves_blocks_alone_when_slug_matches_already(user):
    PageFactory(user=user, title="Python", slug="python")
    block = BlockFactory(user=user, content="hello #python")
    _run("--fix")
    block.refresh_from_db()
    assert block.content == "hello #python"
    # And no phantom updates.
    assert Block.objects.count() == 1
