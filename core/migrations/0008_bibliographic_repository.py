import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_historialpreciolibro_preciolibrotienda'),
    ]

    operations = [
        migrations.CreateModel(
            name='KBProjection',
            fields=[
                ('id', models.CharField(editable=False, max_length=64, primary_key=True, serialize=False)),
                ('last_rowid', models.PositiveBigIntegerField(default=0)),
                ('counters', models.JSONField(default=dict)),
                ('lease_token', models.CharField(blank=True, default='', max_length=64)),
                ('lease_until', models.DateTimeField(null=True)),
                ('updated_at', models.DateTimeField(auto_now=True, db_index=True)),
            ],
        ),
        migrations.CreateModel(
            name='KBRecord',
            fields=[
                ('id', models.CharField(editable=False, max_length=64, primary_key=True, serialize=False)),
                ('provider', models.CharField(max_length=24)),
                ('external_id', models.CharField(max_length=160)),
                ('kind', models.CharField(max_length=16)),
                ('label', models.CharField(max_length=220)),
                ('payload', models.JSONField(default=dict)),
                ('checksum', models.CharField(max_length=64)),
                ('revision', models.PositiveBigIntegerField(default=1)),
                ('status', models.CharField(default='source_metadata', max_length=24)),
                ('source_url', models.URLField(max_length=1024)),
                ('policy', models.CharField(max_length=100)),
                ('license', models.CharField(max_length=180)),
                ('retrieved_at', models.DateTimeField()),
                ('verified_at', models.DateTimeField(null=True)),
                ('stored_bytes', models.PositiveBigIntegerField(default=0)),
            ],
            options={
                'indexes': [models.Index(fields=['provider', 'kind'], name='kb_provider_kind')],
            },
        ),
        migrations.CreateModel(
            name='KBName',
            fields=[
                ('id', models.CharField(editable=False, max_length=64, primary_key=True, serialize=False)),
                ('normalized', models.CharField(db_index=True, max_length=255)),
                ('current', models.BooleanField(default=True)),
                ('record', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='names', to='core.kbrecord')),
            ],
        ),
        migrations.CreateModel(
            name='KBRelation',
            fields=[
                ('id', models.CharField(editable=False, max_length=64, primary_key=True, serialize=False)),
                ('predicate', models.CharField(max_length=32)),
                ('target_id', models.CharField(db_index=True, max_length=64)),
                ('target_external_id', models.CharField(max_length=160)),
                ('current', models.BooleanField(default=True)),
                ('record', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='relations', to='core.kbrecord')),
            ],
        ),
        migrations.CreateModel(
            name='KBVersion',
            fields=[
                ('id', models.CharField(editable=False, max_length=64, primary_key=True, serialize=False)),
                ('checksum', models.CharField(max_length=64)),
                ('payload', models.JSONField(default=dict)),
                ('source_revision', models.PositiveBigIntegerField()),
                ('retrieved_at', models.DateTimeField()),
                ('stored_bytes', models.PositiveBigIntegerField(default=0)),
                ('record', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='versions', to='core.kbrecord')),
            ],
        ),
    ]
