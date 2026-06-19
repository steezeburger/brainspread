import json

from django.test import TestCase
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core.test.helpers import UserFactory
from knowledge.models import Block, Page
from knowledge.repositories import PageRepository
from knowledge.test.helpers import BlockFactory, PageFactory


def _rpc(method: str, params: dict | None = None, req_id: int | str = 1) -> dict:
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def _tool_call(name: str, arguments: dict) -> dict:
    return _rpc("tools/call", {"name": name, "arguments": arguments})


def _content_json(response_body: dict) -> dict:
    """Pull the JSON-serialized payload out of a tools/call result."""
    return json.loads(response_body["result"]["content"][0]["text"])


class MCPEndpointTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="mcp-user@example.com")

    def setUp(self):
        self.client = APIClient()
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    # --- auth + protocol ----------------------------------------------

    def test_requires_authentication(self):
        self.client.credentials()
        response = self.client.post("/api/mcp/", _rpc("initialize"), format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_initialize_returns_server_info(self):
        response = self.client.post(
            "/api/mcp/",
            _rpc("initialize", {"protocolVersion": "2025-06-18"}),
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], 1)
        self.assertEqual(body["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(body["result"]["serverInfo"]["name"], "brainspread")
        self.assertIn("tools", body["result"]["capabilities"])

    def test_initialize_falls_back_to_latest_version_for_unknown(self):
        response = self.client.post(
            "/api/mcp/",
            _rpc("initialize", {"protocolVersion": "1999-01-01"}),
            format="json",
        )
        self.assertEqual(response.json()["result"]["protocolVersion"], "2025-06-18")

    def test_notification_returns_no_content(self):
        # No id ⇒ notification ⇒ no body per JSON-RPC.
        response = self.client.post(
            "/api/mcp/",
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_unknown_method_returns_jsonrpc_error(self):
        response = self.client.post(
            "/api/mcp/", _rpc("does/not/exist"), format="json"
        )
        body = response.json()
        self.assertEqual(body["error"]["code"], -32601)

    def test_tools_list_includes_all_registered_tools(self):
        response = self.client.post("/api/mcp/", _rpc("tools/list"), format="json")
        names = {t["name"] for t in response.json()["result"]["tools"]}
        self.assertSetEqual(
            names,
            {
                "create_todo",
                "create_note",
                "create_page",
                "list_today_todos",
                "get_page",
                "search_notes",
                "toggle_todo",
                "schedule_block",
            },
        )

    def test_batch_request(self):
        response = self.client.post(
            "/api/mcp/",
            [_rpc("initialize", req_id=1), _rpc("tools/list", req_id=2)],
            format="json",
        )
        body = response.json()
        self.assertEqual(len(body), 2)
        self.assertEqual({r["id"] for r in body}, {1, 2})

    # --- create_todo ---------------------------------------------------

    def test_create_todo_creates_block_on_today_page(self):
        response = self.client.post(
            "/api/mcp/",
            _tool_call("create_todo", {"content": "call the dentist"}),
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["result"]["isError"])

        payload = _content_json(body)
        self.assertEqual(payload["block"]["content"], "call the dentist")
        self.assertEqual(payload["block"]["block_type"], "todo")
        self.assertEqual(payload["page"]["page_type"], "daily")

        block = Block.objects.get(uuid=payload["block"]["uuid"])
        self.assertEqual(block.user, self.user)
        self.assertEqual(block.block_type, "todo")

    def test_create_todo_rejects_empty_content(self):
        response = self.client.post(
            "/api/mcp/",
            _tool_call("create_todo", {"content": "   "}),
            format="json",
        )
        body = response.json()
        self.assertTrue(body["result"]["isError"])
        self.assertIn("content", body["result"]["content"][0]["text"])

    # --- create_note ---------------------------------------------------

    def test_create_note_appends_to_today_by_default(self):
        response = self.client.post(
            "/api/mcp/",
            _tool_call("create_note", {"content": "random thought"}),
            format="json",
        )
        payload = _content_json(response.json())
        self.assertEqual(payload["block"]["block_type"], "bullet")
        self.assertEqual(payload["page"]["page_type"], "daily")

    def test_create_note_targets_explicit_page_slug(self):
        page = PageFactory(user=self.user, slug="project-foo", title="Project Foo")
        response = self.client.post(
            "/api/mcp/",
            _tool_call(
                "create_note",
                {"content": "design idea", "page_slug": "project-foo"},
            ),
            format="json",
        )
        payload = _content_json(response.json())
        self.assertEqual(payload["page"]["uuid"], str(page.uuid))
        self.assertEqual(payload["block"]["page_uuid"], str(page.uuid))

    # --- create_page ---------------------------------------------------

    def test_create_page(self):
        response = self.client.post(
            "/api/mcp/",
            _tool_call("create_page", {"title": "My Plan"}),
            format="json",
        )
        payload = _content_json(response.json())
        self.assertEqual(payload["title"], "My Plan")
        self.assertEqual(payload["slug"], "my-plan")
        self.assertTrue(Page.objects.filter(user=self.user, slug="my-plan").exists())

    # --- list_today_todos ---------------------------------------------

    def test_list_today_todos_filters_to_undone(self):
        today = self.user.today()
        # Use the repository helper so this matches the same daily page
        # the view resolves via GetPageWithBlocksCommand (which keys off
        # slug=YYYY-MM-DD, not date+page_type).
        page, _ = PageRepository.get_or_create_daily_note(self.user, today)
        BlockFactory(user=self.user, page=page, content="do thing", block_type="todo")
        BlockFactory(user=self.user, page=page, content="already done", block_type="done")
        BlockFactory(user=self.user, page=page, content="note", block_type="bullet")

        response = self.client.post(
            "/api/mcp/", _tool_call("list_today_todos", {}), format="json"
        )
        payload = _content_json(response.json())
        contents = {b["content"] for b in payload["undone_today"]}
        self.assertEqual(contents, {"do thing"})

    # --- get_page ------------------------------------------------------

    def test_get_page_by_slug_returns_blocks(self):
        page = PageFactory(user=self.user, slug="g", title="G")
        BlockFactory(user=self.user, page=page, content="hello", order=1)
        response = self.client.post(
            "/api/mcp/", _tool_call("get_page", {"slug": "g"}), format="json"
        )
        payload = _content_json(response.json())
        self.assertEqual(payload["page"]["slug"], "g")
        contents = [b["content"] for b in payload["direct_blocks"]]
        self.assertIn("hello", contents)

    def test_get_page_user_isolation(self):
        other = UserFactory(email="other@example.com")
        PageFactory(user=other, slug="secret", title="Secret")
        response = self.client.post(
            "/api/mcp/", _tool_call("get_page", {"slug": "secret"}), format="json"
        )
        # Other user's page is not visible to us.
        self.assertTrue(response.json()["result"]["isError"])

    # --- search_notes --------------------------------------------------

    def test_search_notes_finds_match(self):
        page = PageFactory(user=self.user)
        BlockFactory(user=self.user, page=page, content="meeting with bob")
        BlockFactory(user=self.user, page=page, content="grocery list")
        response = self.client.post(
            "/api/mcp/",
            _tool_call("search_notes", {"query": "meeting"}),
            format="json",
        )
        payload = _content_json(response.json())
        # SearchNotesCommand shape: {"results": [...]} or similar — assert
        # the matching content shows up regardless of exact envelope.
        text = json.dumps(payload)
        self.assertIn("meeting with bob", text)
        self.assertNotIn("grocery list", text)

    # --- toggle_todo ---------------------------------------------------

    def test_toggle_todo_cycles_state(self):
        page = PageFactory(user=self.user)
        block = BlockFactory(
            user=self.user, page=page, content="ship it", block_type="todo"
        )
        response = self.client.post(
            "/api/mcp/",
            _tool_call("toggle_todo", {"block_uuid": str(block.uuid)}),
            format="json",
        )
        payload = _content_json(response.json())
        block.refresh_from_db()
        # Toggle should leave the block in a non-`todo` state (doing or done,
        # depending on starting state) — just confirm something changed.
        self.assertNotEqual(payload["block_type"], "todo")

    def test_toggle_todo_rejects_other_users_block(self):
        other = UserFactory(email="o@example.com")
        block = BlockFactory(user=other, block_type="todo")
        response = self.client.post(
            "/api/mcp/",
            _tool_call("toggle_todo", {"block_uuid": str(block.uuid)}),
            format="json",
        )
        self.assertTrue(response.json()["result"]["isError"])

    # --- schedule_block ------------------------------------------------

    def test_schedule_block_sets_scheduled_for(self):
        page = PageFactory(user=self.user)
        block = BlockFactory(user=self.user, page=page, block_type="todo")
        response = self.client.post(
            "/api/mcp/",
            _tool_call(
                "schedule_block",
                {"block_uuid": str(block.uuid), "scheduled_for": "2026-07-15"},
            ),
            format="json",
        )
        body = response.json()
        self.assertFalse(body["result"]["isError"], body)
        block.refresh_from_db()
        self.assertEqual(block.scheduled_for.isoformat(), "2026-07-15")

    def test_unknown_tool_returns_tool_error(self):
        response = self.client.post(
            "/api/mcp/", _tool_call("does_not_exist", {}), format="json"
        )
        body = response.json()
        self.assertTrue(body["result"]["isError"])
        self.assertIn("does_not_exist", body["result"]["content"][0]["text"])
