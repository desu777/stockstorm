# Generated by Django 5.1.4 on 2024-12-28 15:09

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0004_bot'),
    ]

    operations = [
        migrations.AddField(
            model_name='bot',
            name='stream_session_id',
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
    ]
