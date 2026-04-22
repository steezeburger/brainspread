import factory
from factory import Faker, SubFactory
from factory.django import DjangoModelFactory

from core.test.helpers import UserFactory
from knowledge.models import Block, Page


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
