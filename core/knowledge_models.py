"""Registros bibliográficos de fuente, separados del catálogo y datos de lectores.

Una edición no es una obra. Dos fuentes no se fusionan por título/autor.
Los hechos narrativos y su revisión siguen en literary_memory, no en estos JSON.
"""
from django.db import models


class KBRecord(models.Model):
    id = models.CharField(primary_key=True, max_length=64, editable=False)
    provider = models.CharField(max_length=24)
    external_id = models.CharField(max_length=160)
    kind = models.CharField(max_length=16)
    label = models.CharField(max_length=220)
    payload = models.JSONField(default=dict)
    checksum = models.CharField(max_length=64)
    revision = models.PositiveBigIntegerField(default=1)
    status = models.CharField(max_length=24, default='source_metadata')
    source_url = models.URLField(max_length=1024)
    policy = models.CharField(max_length=100)
    license = models.CharField(max_length=180)
    retrieved_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True)  # Revisión explícita del operador; NULL al importar.
    stored_bytes = models.PositiveBigIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=['provider', 'kind'], name='kb_provider_kind')]


class KBName(models.Model):
    id = models.CharField(primary_key=True, max_length=64, editable=False)
    record = models.ForeignKey(KBRecord, on_delete=models.PROTECT, related_name='names')
    normalized = models.CharField(max_length=255, db_index=True)
    current = models.BooleanField(default=True)


class KBRelation(models.Model):
    id = models.CharField(primary_key=True, max_length=64, editable=False)
    record = models.ForeignKey(KBRecord, on_delete=models.PROTECT, related_name='relations')
    predicate = models.CharField(max_length=32)
    target_id = models.CharField(max_length=64, db_index=True)
    target_external_id = models.CharField(max_length=160)
    current = models.BooleanField(default=True)
    # Referencias aún no importadas son válidas; nunca inventar sus etiquetas.


class KBVersion(models.Model):
    id = models.CharField(primary_key=True, max_length=64, editable=False)
    record = models.ForeignKey(KBRecord, on_delete=models.PROTECT, related_name='versions')
    checksum = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    source_revision = models.PositiveBigIntegerField()
    retrieved_at = models.DateTimeField()
    stored_bytes = models.PositiveBigIntegerField(default=0)


class KBProjection(models.Model):
    id = models.CharField(primary_key=True, max_length=64, editable=False)
    last_rowid = models.PositiveBigIntegerField(default=0)
    counters = models.JSONField(default=dict)
    lease_token = models.CharField(max_length=64, blank=True, default='')
    lease_until = models.DateTimeField(null=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
