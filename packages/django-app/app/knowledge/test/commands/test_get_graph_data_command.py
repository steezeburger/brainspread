from django.test import TestCase

from knowledge.commands import GetGraphDataCommand
from knowledge.forms import GetGraphDataForm

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestGetGraphDataCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.other_user = UserFactory()

    def _build_form(self, include_daily: bool = False, include_orphans: bool = True):
        form = GetGraphDataForm(
            {
                "user": self.user.id,
                "include_daily": "true" if include_daily else "false",
                "include_orphans": "true" if include_orphans else "false",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        return form

    def test_returns_empty_graph_when_user_has_no_pages(self):
        form = self._build_form()
        result = GetGraphDataCommand(form).execute()

        self.assertEqual(result["nodes"], [])
        self.assertEqual(result["edges"], [])

    def test_returns_nodes_for_user_pages_excluding_daily_by_default(self):
        page_a = PageFactory(user=self.user, title="Alpha", slug="alpha")
        PageFactory(user=self.user, title="Daily", slug="daily", page_type="daily")
        # Another user's pages should never appear
        PageFactory(user=self.other_user, title="Leak", slug="leak")

        form = self._build_form()
        result = GetGraphDataCommand(form).execute()

        uuids = {n["uuid"] for n in result["nodes"]}
        self.assertIn(str(page_a.uuid), uuids)
        self.assertEqual(len(result["nodes"]), 1)

    def test_includes_daily_when_requested(self):
        PageFactory(user=self.user, title="Alpha", slug="alpha")
        PageFactory(user=self.user, title="Daily", slug="daily", page_type="daily")

        form = self._build_form(include_daily=True)
        result = GetGraphDataCommand(form).execute()

        slugs = {n["slug"] for n in result["nodes"]}
        self.assertSetEqual(slugs, {"alpha", "daily"})

    def test_builds_edges_from_block_page_tags(self):
        page_a = PageFactory(user=self.user, title="Alpha", slug="alpha")
        page_b = PageFactory(user=self.user, title="Beta", slug="beta")

        block = BlockFactory(user=self.user, page=page_a, content="has #beta tag")
        block.pages.add(page_b)

        form = self._build_form()
        result = GetGraphDataCommand(form).execute()

        self.assertEqual(len(result["edges"]), 1)
        edge = result["edges"][0]
        self.assertEqual(edge["source"], str(page_a.uuid))
        self.assertEqual(edge["target"], str(page_b.uuid))
        self.assertEqual(edge["weight"], 1)

        degrees = {n["uuid"]: n["degree"] for n in result["nodes"]}
        self.assertEqual(degrees[str(page_a.uuid)], 1)
        self.assertEqual(degrees[str(page_b.uuid)], 1)

    def test_builds_edges_from_wiki_links(self):
        page_a = PageFactory(user=self.user, title="Alpha", slug="alpha")
        page_b = PageFactory(user=self.user, title="Beta", slug="beta")

        BlockFactory(
            user=self.user,
            page=page_a,
            content="See [[Beta]] and [[beta]] for details",
        )

        form = self._build_form()
        result = GetGraphDataCommand(form).execute()

        edges = [(e["source"], e["target"], e["weight"]) for e in result["edges"]]
        self.assertIn((str(page_a.uuid), str(page_b.uuid), 2), edges)

    def test_aggregates_multiple_edges_between_same_pages(self):
        page_a = PageFactory(user=self.user, title="Alpha", slug="alpha")
        page_b = PageFactory(user=self.user, title="Beta", slug="beta")

        block1 = BlockFactory(user=self.user, page=page_a, content="first")
        block1.pages.add(page_b)
        block2 = BlockFactory(user=self.user, page=page_a, content="second [[Beta]]")
        block2.pages.add(page_b)

        form = self._build_form()
        result = GetGraphDataCommand(form).execute()

        matching = [
            e
            for e in result["edges"]
            if e["source"] == str(page_a.uuid) and e["target"] == str(page_b.uuid)
        ]
        self.assertEqual(len(matching), 1)
        # two tag edges + one wiki-link match = weight 3
        self.assertEqual(matching[0]["weight"], 3)

    def test_links_cooccurring_tags_even_when_host_page_is_excluded(self):
        page_a = PageFactory(user=self.user, title="Alpha", slug="alpha")
        page_b = PageFactory(user=self.user, title="Beta", slug="beta")
        daily = PageFactory(
            user=self.user, title="Daily", slug="2024-01-01", page_type="daily"
        )

        block = BlockFactory(user=self.user, page=daily, content="#alpha #beta")
        block.pages.add(page_a)
        block.pages.add(page_b)

        form = self._build_form()
        result = GetGraphDataCommand(form).execute()

        a_uuid = str(page_a.uuid)
        b_uuid = str(page_b.uuid)
        expected_src, expected_tgt = (
            (a_uuid, b_uuid) if a_uuid < b_uuid else (b_uuid, a_uuid)
        )
        edges = [(e["source"], e["target"], e["weight"]) for e in result["edges"]]
        self.assertIn((expected_src, expected_tgt, 1), edges)

    def test_cooccurrence_edges_scale_with_tag_count(self):
        page_a = PageFactory(user=self.user, title="Alpha", slug="alpha")
        page_b = PageFactory(user=self.user, title="Beta", slug="beta")
        page_c = PageFactory(user=self.user, title="Gamma", slug="gamma")
        host = PageFactory(user=self.user, title="Host", slug="host")

        block = BlockFactory(user=self.user, page=host, content="#alpha #beta #gamma")
        block.pages.add(page_a)
        block.pages.add(page_b)
        block.pages.add(page_c)

        form = self._build_form()
        result = GetGraphDataCommand(form).execute()

        tag_uuids = {str(page_a.uuid), str(page_b.uuid), str(page_c.uuid)}
        cooccurrence_edges = [
            e
            for e in result["edges"]
            if e["source"] in tag_uuids and e["target"] in tag_uuids
        ]
        self.assertEqual(len(cooccurrence_edges), 3)

    def test_excludes_self_loops(self):
        page_a = PageFactory(user=self.user, title="Alpha", slug="alpha")
        block = BlockFactory(
            user=self.user, page=page_a, content="Self reference [[Alpha]]"
        )
        block.pages.add(page_a)

        form = self._build_form()
        result = GetGraphDataCommand(form).execute()

        self.assertEqual(result["edges"], [])

    def test_include_orphans_false_drops_unconnected_pages(self):
        page_a = PageFactory(user=self.user, title="Alpha", slug="alpha")
        page_b = PageFactory(user=self.user, title="Beta", slug="beta")
        PageFactory(user=self.user, title="Orphan", slug="orphan")

        block = BlockFactory(user=self.user, page=page_a, content="link")
        block.pages.add(page_b)

        form = self._build_form(include_orphans=False)
        result = GetGraphDataCommand(form).execute()

        slugs = {n["slug"] for n in result["nodes"]}
        self.assertSetEqual(slugs, {"alpha", "beta"})

    def test_excludes_other_users_edges(self):
        page_a = PageFactory(user=self.user, title="Alpha", slug="alpha")
        page_b = PageFactory(user=self.user, title="Beta", slug="beta")

        other_page = PageFactory(user=self.other_user, title="Other", slug="other")
        other_block = BlockFactory(
            user=self.other_user, page=other_page, content="hidden"
        )
        # Cross-user M2M should not appear for self.user's graph
        other_block.pages.add(page_b)

        form = self._build_form()
        result = GetGraphDataCommand(form).execute()

        self.assertEqual(result["edges"], [])
        uuids = {n["uuid"] for n in result["nodes"]}
        self.assertSetEqual(uuids, {str(page_a.uuid), str(page_b.uuid)})
