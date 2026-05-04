from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_alter_user_time_format"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="theme",
            field=models.CharField(
                choices=[
                    ("dark", "Dark"),
                    ("light", "Light"),
                    ("solarized_dark", "Solarized Dark"),
                    ("purple", "Purple"),
                    ("earthy", "Earthy"),
                    ("forest", "Forest"),
                    ("staging", "Staging"),
                ],
                default="dark",
                help_text="User's preferred theme",
                max_length=20,
                verbose_name="theme",
            ),
        ),
    ]
