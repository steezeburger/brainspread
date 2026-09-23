"""Custom variable CRUD commands and their use at the token binding
points (issue #228)."""

import re

from django.core.exceptions import ValidationError
from django.test import TestCase

from knowledge.commands import (
    AddTemplateBlocksToPageCommand,
    CreateBlockCommand,
    CreateCustomVariableCommand,
    DeleteCustomVariableCommand,
    ListCustomVariablesCommand,
    UpdateBlockCommand,
    UpdateCustomVariableCommand,
)
from knowledge.forms import (
    AddTemplateBlocksToPageForm,
    CreateBlockForm,
    CreateCustomVariableForm,
    DeleteCustomVariableForm,
    ListCustomVariablesForm,
    UpdateBlockForm,
    UpdateCustomVariableForm,
)
from knowledge.models import Block, CustomVariable

from ..helpers import BlockFactory, CustomVariableFactory, PageFactory, UserFactory


def _create(user, name, expansion):
    form = CreateCustomVariableForm(
        {"user": user.id, "name": name, "expansion": expansion}
    )
    assert form.is_valid(), form.errors
    return CreateCustomVariableCommand(form).execute()


def _update(user, variable, **fields):
    form = UpdateCustomVariableForm(
        {"user": user.id, "variable_uuid": str(variable.uuid), **fields}
    )
    assert form.is_valid(), form.errors
    return UpdateCustomVariableCommand(form).execute()


class CreateCustomVariableTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def test_creates_variable(self):
        variable = _create(self.user, "food_log", "{{current_time}} #food-log")
        self.assertEqual(variable.user, self.user)
        self.assertEqual(variable.name, "food_log")
        self.assertEqual(variable.expansion, "{{current_time}} #food-log")

    def test_normalizes_case_and_surrounding_braces(self):
        variable = _create(self.user, " {{Food_Log}} ", "x")
        self.assertEqual(variable.name, "food_log")

    def test_rejects_builtin_names(self):
        for name in ("today", "current_time", "uuid", "input", "count"):
            with self.subTest(name=name):
                with self.assertRaisesMessage(ValidationError, "built-in"):
                    _create(self.user, name, "x")

    def test_rejects_malformed_names(self):
        for name in ("page.title", "has space", "1abc", "a-b", "a:b", "_x"):
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    _create(self.user, name, "x")

    def test_rejects_duplicate_name_for_same_user(self):
        CustomVariableFactory(user=self.user, name="stack")
        with self.assertRaisesMessage(ValidationError, "already have"):
            _create(self.user, "stack", "x")

    def test_same_name_allowed_for_different_users(self):
        CustomVariableFactory(user=UserFactory(), name="stack")
        self.assertEqual(_create(self.user, "stack", "x").name, "stack")

    def test_rejects_self_reference(self):
        with self.assertRaisesMessage(ValidationError, "a → a"):
            _create(self.user, "a", "{{a}}")

    def test_rejects_mutual_reference(self):
        _create(self.user, "a", "{{b}}")
        with self.assertRaisesMessage(ValidationError, "b → a → b"):
            _create(self.user, "b", "{{a}}")
        self.assertFalse(CustomVariable.objects.filter(name="b").exists())

    def test_requires_expansion(self):
        form = CreateCustomVariableForm(
            {"user": self.user.id, "name": "x", "expansion": ""}
        )
        self.assertFalse(form.is_valid())


class UpdateCustomVariableTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def test_updates_name_and_expansion(self):
        variable = CustomVariableFactory(user=self.user, name="old", expansion="a")
        updated = _update(self.user, variable, name="new", expansion="b")
        self.assertEqual((updated.name, updated.expansion), ("new", "b"))

    def test_partial_update_keeps_other_field(self):
        variable = CustomVariableFactory(user=self.user, name="keep", expansion="a")
        updated = _update(self.user, variable, expansion="b")
        self.assertEqual((updated.name, updated.expansion), ("keep", "b"))

    def test_keeping_own_name_is_not_a_duplicate(self):
        variable = CustomVariableFactory(user=self.user, name="same")
        self.assertEqual(_update(self.user, variable, name="same").name, "same")

    def test_rejects_rename_onto_builtin_or_existing(self):
        variable = CustomVariableFactory(user=self.user, name="mine")
        CustomVariableFactory(user=self.user, name="taken")
        with self.assertRaises(ValidationError):
            _update(self.user, variable, name="now")
        with self.assertRaises(ValidationError):
            _update(self.user, variable, name="taken")

    def test_rejects_edit_that_creates_cycle(self):
        a = CustomVariableFactory(user=self.user, name="a", expansion="{{b}}")
        CustomVariableFactory(user=self.user, name="b", expansion="plain")
        b = CustomVariable.objects.get(name="b")
        with self.assertRaisesMessage(ValidationError, "b → a → b"):
            _update(self.user, b, expansion="{{a}}")
        a.refresh_from_db()
        self.assertEqual(a.expansion, "{{b}}")

    def test_other_users_variable_not_found(self):
        variable = CustomVariableFactory(user=UserFactory())
        with self.assertRaisesMessage(ValidationError, "not found"):
            _update(self.user, variable, expansion="x")


class DeleteAndListCustomVariableTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def test_delete(self):
        variable = CustomVariableFactory(user=self.user)
        form = DeleteCustomVariableForm(
            {"user": self.user.id, "variable_uuid": str(variable.uuid)}
        )
        self.assertTrue(form.is_valid(), form.errors)
        DeleteCustomVariableCommand(form).execute()
        self.assertFalse(CustomVariable.objects.filter(pk=variable.pk).exists())

    def test_delete_other_users_variable_not_found(self):
        variable = CustomVariableFactory(user=UserFactory())
        form = DeleteCustomVariableForm(
            {"user": self.user.id, "variable_uuid": str(variable.uuid)}
        )
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertRaises(ValidationError):
            DeleteCustomVariableCommand(form).execute()
        self.assertTrue(CustomVariable.objects.filter(pk=variable.pk).exists())

    def test_list_returns_only_own_sorted_by_name(self):
        CustomVariableFactory(user=self.user, name="zeta")
        CustomVariableFactory(user=self.user, name="alpha")
        CustomVariableFactory(user=UserFactory(), name="other")
        form = ListCustomVariablesForm({"user": self.user.id})
        self.assertTrue(form.is_valid(), form.errors)
        names = [v.name for v in ListCustomVariablesCommand(form).execute()]
        self.assertEqual(names, ["alpha", "zeta"])


class CustomVariableBindingPointTests(TestCase):
    """Custom variables resolve (recursively) at block save and template
    apply, against the saving user's own definitions."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(time_format="24h")
        cls.page = PageFactory(user=cls.user)
        CustomVariableFactory(
            user=cls.user, name="stack", expansion="sabroxy, tongkat, omegaTAU"
        )
        CustomVariableFactory(
            user=cls.user,
            name="daily_mood_stack_log",
            expansion="{{stack}} @ {{current_time}} #supplements",
        )

    def _create_block(self, content, user=None, page=None):
        form = CreateBlockForm(
            {
                "user": (user or self.user).id,
                "page": (page or self.page).uuid,
                "content": content,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        return CreateBlockCommand(form).execute()

    def test_block_save_expands_nested_variables(self):
        block = self._create_block("{{daily_mood_stack_log}}")
        self.assertRegex(
            block.content,
            r"^sabroxy, tongkat, omegaTAU @ \d{2}:\d{2} #supplements$",
        )
        # The tag carried by the expansion gets synced like typed text.
        self.assertIn("supplements", [t.slug for t in block.get_tags()])

    def test_block_update_expands_variables(self):
        block = BlockFactory(user=self.user, page=self.page, content="x")
        form = UpdateBlockForm(
            {"user": self.user.id, "block": block.uuid, "content": "{{stack}}"}
        )
        self.assertTrue(form.is_valid(), form.errors)
        block = UpdateBlockCommand(form).execute()
        self.assertEqual(block.content, "sabroxy, tongkat, omegaTAU")

    def test_other_users_variables_are_not_visible(self):
        stranger = UserFactory()
        page = PageFactory(user=stranger)
        with self.assertRaisesMessage(ValidationError, "unknown token"):
            self._create_block("{{stack}}", user=stranger, page=page)

    def test_template_apply_expands_variables_and_nested_inputs(self):
        CustomVariableFactory(
            user=self.user, name="rate_mood", expansion="mood: {{input:Mood}}"
        )
        template = PageFactory(user=self.user, page_type="template")
        BlockFactory(
            user=self.user,
            page=template,
            content="{{rate_mood}} / {{stack}}",
            order=0,
        )
        target = PageFactory(user=self.user)

        def apply(inputs=None):
            data = {
                "user": self.user.id,
                "template": template.uuid,
                "target_page": target.uuid,
            }
            if inputs is not None:
                data["inputs"] = inputs
            form = AddTemplateBlocksToPageForm(data)
            self.assertTrue(form.is_valid(), form.errors)
            return AddTemplateBlocksToPageCommand(form).execute()

        self.assertEqual(apply()["needs_input"], ["Mood"])
        self.assertEqual(apply({"Mood": "great"})["added"], 1)
        cloned = Block.objects.get(page=target)
        self.assertEqual(cloned.content, "mood: great / sabroxy, tongkat, omegaTAU")

    def test_template_page_keeps_variables_dormant(self):
        template = PageFactory(user=self.user, page_type="template")
        block = self._create_block("{{stack}}", page=template)
        self.assertEqual(block.content, "{{stack}}")

    def test_cycle_created_outside_commands_fails_block_save_cleanly(self):
        CustomVariableFactory(user=self.user, name="loop_a", expansion="{{loop_b}}")
        CustomVariableFactory(user=self.user, name="loop_b", expansion="{{loop_a}}")
        with self.assertRaises(ValidationError) as cm:
            self._create_block("{{loop_a}}")
        self.assertTrue(
            re.search(r"cycle: loop_a → loop_b → loop_a", str(cm.exception))
        )
