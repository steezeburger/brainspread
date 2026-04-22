from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("ai_chat", "0013_pendingtoolapproval"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="aimodel",
            options={
                "ordering": ["provider__name", "name"],
                "verbose_name": "AI Model",
                "verbose_name_plural": "AI Models",
            },
        ),
        migrations.AlterModelOptions(
            name="aiprovider",
            options={
                "ordering": ("name",),
                "verbose_name": "AI Provider",
                "verbose_name_plural": "AI Providers",
            },
        ),
        migrations.AlterModelOptions(
            name="chatmessage",
            options={
                "ordering": ("created_at",),
                "verbose_name": "Chat Message",
                "verbose_name_plural": "Chat Messages",
            },
        ),
        migrations.AlterModelOptions(
            name="chatsession",
            options={
                "ordering": ("-created_at",),
                "verbose_name": "Chat Session",
                "verbose_name_plural": "Chat Sessions",
            },
        ),
        migrations.AlterModelOptions(
            name="pendingtoolapproval",
            options={
                "ordering": ("-created_at",),
                "verbose_name": "Pending Tool Approval",
                "verbose_name_plural": "Pending Tool Approvals",
            },
        ),
        migrations.AlterModelOptions(
            name="useraisettings",
            options={
                "verbose_name": "User AI Settings",
                "verbose_name_plural": "User AI Settings",
            },
        ),
        migrations.AlterModelOptions(
            name="userproviderconfig",
            options={
                "verbose_name": "User Provider Config",
                "verbose_name_plural": "User Provider Configs",
            },
        ),
    ]
