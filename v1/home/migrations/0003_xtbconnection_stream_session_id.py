# Generated by Django 5.1.4 on 2024-12-20 13:48

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0002_xtbconnection_delete_xtbaccount'),
    ]

    operations = [
        migrations.AddField(
            model_name='xtbconnection',
            name='stream_session_id',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
