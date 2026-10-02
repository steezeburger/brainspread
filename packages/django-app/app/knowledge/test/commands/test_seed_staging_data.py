from io import StringIO

import pytest
from django.core.management import call_command

from knowledge.constants import COMPLETED_TODO_TYPES
from knowledge.models import Block
from knowledge.test.helpers import UserFactory


@pytest.fixture
def superuser(db):
    return UserFactory(is_superuser=True, is_staff=True)


def _seeded_blocks(user):
    call_command("seed_staging_data", stdout=StringIO())
    return list(Block.objects.filter(user=user))


@pytest.mark.django_db
def test_completed_blocks_carry_a_completed_at(superuser):
    blocks = _seeded_blocks(superuser)
    completed = [b for b in blocks if b.block_type in COMPLETED_TODO_TYPES]
    assert completed
    assert all(b.completed_at is not None for b in completed)


@pytest.mark.django_db
def test_open_blocks_have_no_completed_at(superuser):
    blocks = _seeded_blocks(superuser)
    assert all(
        b.completed_at is None
        for b in blocks
        if b.block_type not in COMPLETED_TODO_TYPES
    )


@pytest.mark.django_db
def test_seeds_no_heading_blocks(superuser):
    blocks = _seeded_blocks(superuser)
    assert blocks
    assert not [b for b in blocks if b.block_type == "heading"]
