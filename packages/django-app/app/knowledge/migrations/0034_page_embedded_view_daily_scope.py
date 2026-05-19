from django.db import migrations, models


def _drop_daily_page_embeds(apps, schema_editor) -> None:
    """Remove embeds attached to daily pages.

    These rows were stored against a specific date's ``Page`` record, so
    they only ever showed on that one day. The new ``scope='daily'``
    semantics replace them — but per the change spec we drop instead of
    migrate, since the prior rows existed under (broken) per-day
    semantics that the user wouldn't expect to inherit.
    """
    PageEmbeddedView = apps.get_model("knowledge", "PageEmbeddedView")
    PageEmbeddedView.objects.filter(page__page_type="daily").delete()


def _noop_reverse(apps, schema_editor) -> None:
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0033_savedview_pinned"),
    ]

    operations = [
        migrations.RunPython(_drop_daily_page_embeds, _noop_reverse),
        migrations.AddField(
            model_name="pageembeddedview",
            name="scope",
            field=models.CharField(
                choices=[("page", "Page"), ("daily", "Daily")],
                default="page",
                help_text=(
                    "'page' = pinned to one specific Page; 'daily' = "
                    "pinned to the daily page concept, renders on "
                    "whichever daily is open"
                ),
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="pageembeddedview",
            name="page",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.CASCADE,
                related_name="embedded_views",
                to="knowledge.page",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="pageembeddedview",
            unique_together=set(),
        ),
        migrations.RemoveIndex(
            model_name="pageembeddedview",
            name="page_embed_user_idx",
        ),
        migrations.AddIndex(
            model_name="pageembeddedview",
            index=models.Index(
                fields=["user", "scope"], name="page_embed_user_scope_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="pageembeddedview",
            constraint=models.UniqueConstraint(
                condition=models.Q(("scope", "page")),
                fields=("page", "saved_view"),
                name="uniq_embed_page_view_page_scope",
            ),
        ),
        migrations.AddConstraint(
            model_name="pageembeddedview",
            constraint=models.UniqueConstraint(
                condition=models.Q(("scope", "daily")),
                fields=("user", "saved_view"),
                name="uniq_embed_user_view_daily_scope",
            ),
        ),
    ]
