from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("ai_chat", "0009_chatmessage_ai_model"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="useraisettings",
            options={
                "verbose_name": "user AI settings",
                "verbose_name_plural": "user AI settings",
            },
        ),
    ]
