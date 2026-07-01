from datetime import date, datetime
from datetime import time as time_cls

import factory
import pytz
from factory import Faker, SubFactory
from factory.django import DjangoModelFactory

from core.test.helpers import UserFactory
from knowledge.models import Block, Page


def due_dt(
    *args: "date | int", tz: str = "UTC", hour: int = 0, minute: int = 0
) -> datetime:
    """Build a Block.due_at value for tests.

    due_at is a datetime; an all-day due is stored at user-local midnight.
    Accepts either ``due_dt(year, month, day)`` or ``due_dt(date_obj)`` so a
    ``scheduled_for=date(...)`` site rewrites cleanly to ``due_at=due_dt(...)``.
    Pass ``tz`` to match the test user's timezone (default UTC) and
    ``hour``/``minute`` for a timed due.
    """
    if len(args) == 1 and isinstance(args[0], date):
        d = args[0]
    else:
        d = date(*args)
    naive = datetime.combine(d, time_cls(hour, minute))
    return pytz.timezone(tz).localize(naive).astimezone(pytz.UTC)


class PageFactory(DjangoModelFactory):
    uuid = factory.Faker("uuid4")
    user = SubFactory(UserFactory)
    title = Faker("sentence", nb_words=3)
    slug = factory.LazyAttribute(
        lambda obj: obj.title.lower().replace(" ", "-").replace(".", "")
    )
    # whiteboard_snapshot deliberately defaults to "" — only whiteboard
    # pages populate it, and tests that need one should pass it explicitly.
    is_published = True
    page_type = "page"

    class Meta:
        model = Page


class BlockFactory(DjangoModelFactory):
    uuid = factory.Faker("uuid4")
    user = SubFactory(UserFactory)
    page = SubFactory(PageFactory)
    content = Faker("text", max_nb_chars=100)
    content_type = "text"
    block_type = "bullet"
    order = factory.Sequence(lambda n: n)

    class Meta:
        model = Block
