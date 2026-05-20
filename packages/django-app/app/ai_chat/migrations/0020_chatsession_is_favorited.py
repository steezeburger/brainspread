from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_chat", "0019_chatmessage_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatsession",
            name="is_favorited",
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
