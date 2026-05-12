from io import StringIO

import pytest
from django.core.management import call_command

from knowledge.test.helpers import BlockFactory, PageFactory, UserFactory


@pytest.fixture
def user(db):
    return UserFactory()


@pytest.fixture
def other_user(db):
    return UserFactory()


def _run(*args):
    out = StringIO()
    call_command("fix_orphaned_blocks", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_reports_when_no_orphans(user):
    page = PageFactory(user=user)
    parent = BlockFactory(user=user, page=page, order=1)
    BlockFactory(user=user, page=page, parent=parent, order=2)
    output = _run()
    assert "No orphaned blocks found." in output


@pytest.mark.django_db
def test_dry_run_reports_but_does_not_change_anything(user):
    source_page = PageFactory(user=user, title="source")
    target_page = PageFactory(user=user, title="target")
    parent = BlockFactory(user=user, page=source_page, order=1)
    orphan = BlockFactory(
        user=user, page=target_page, parent=parent, order=5
    )

    output = _run("--dry-run")
    assert "would fix 1 block" in output

    orphan.refresh_from_db()
    assert orphan.parent_id == parent.pk
    assert orphan.order == 5


@pytest.mark.django_db
def test_promotes_orphan_to_root_on_its_own_page(user):
    source_page = PageFactory(user=user, title="source")
    target_page = PageFactory(user=user, title="target")
    parent = BlockFactory(user=user, page=source_page, order=1)
    existing_root = BlockFactory(user=user, page=target_page, order=1)
    orphan = BlockFactory(
        user=user, page=target_page, parent=parent, order=5
    )

    output = _run()
    assert "fixed 1 block" in output

    orphan.refresh_from_db()
    assert orphan.parent is None
    # Lands at the bottom of the target page (max existing root order + 1).
    assert orphan.order == existing_root.order + 1


@pytest.mark.django_db
def test_leaves_correctly_parented_blocks_alone(user):
    page = PageFactory(user=user)
    parent = BlockFactory(user=user, page=page, order=1)
    child = BlockFactory(user=user, page=page, parent=parent, order=2)

    _run()

    child.refresh_from_db()
    assert child.parent_id == parent.pk
    assert child.order == 2


@pytest.mark.django_db
def test_scopes_to_user_when_email_provided(user, other_user):
    # Orphan owned by `user`.
    user_source = PageFactory(user=user, title="user-source")
    user_target = PageFactory(user=user, title="user-target")
    user_parent = BlockFactory(user=user, page=user_source)
    user_orphan = BlockFactory(
        user=user, page=user_target, parent=user_parent
    )

    # Orphan owned by `other_user` — should be skipped when --user filters.
    other_source = PageFactory(user=other_user, title="other-source")
    other_target = PageFactory(user=other_user, title="other-target")
    other_parent = BlockFactory(user=other_user, page=other_source)
    other_orphan = BlockFactory(
        user=other_user, page=other_target, parent=other_parent
    )

    _run("--user", user.email)

    user_orphan.refresh_from_db()
    other_orphan.refresh_from_db()

    assert user_orphan.parent is None
    assert other_orphan.parent_id == other_parent.pk
