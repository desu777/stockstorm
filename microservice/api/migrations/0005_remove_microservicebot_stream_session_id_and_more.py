# Generated by Django 5.1.4 on 2025-01-13 13:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0004_userprofile_auth_token'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='microservicebot',
            name='stream_session_id',
        ),
        migrations.AddField(
            model_name='microservicebot',
            name='xtb_login',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='microservicebot',
            name='xtb_password_enc',
            field=models.BinaryField(blank=True, null=True),
        ),
    ]
