# Generated by Django 5.1.4 on 2025-01-04 22:05

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0003_trade'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='auth_token',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]