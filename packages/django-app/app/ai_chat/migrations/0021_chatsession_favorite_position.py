from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_chat", "0020_chatsession_is_favorited"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatsession",
            name="favorite_position",
            field=models.IntegerField(default=0),
        ),
    ]
