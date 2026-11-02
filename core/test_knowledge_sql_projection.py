"""Exact catalogue anchors, including editions; isolated Django test database."""
from pathlib import Path
from tempfile import TemporaryDirectory
from django.test import TestCase,override_settings
from django.utils import timezone
from .test_narrative_answers import BOOK,PAGE


class KnowledgeProjectionTests(TestCase):
    def test_a_known_edition_keeps_an_evidence_pointer_without_becoming_a_work(self):
        from .knowledge_models import KBRecord,KBRelation
        from .literary_identity import bind_source,stable_work_id
        from .literary_memory import remember_evidence
        from .continuous_knowledge import project_references
        book={**BOOK,'source':'Project Gutenberg','url':'https://www.gutenberg.org/ebooks/999',
            'storage_policy':'gutenberg-catalog-public-domain-v1','license':'CC0-1.0'}
        row=KBRecord.objects.create(id='a'*64,provider='gutenberg',external_id='999',kind='edition',
            label=BOOK['title'],payload={'author':BOOK['author']},checksum='b'*64,status='source_metadata',
            source_url=book['url'],policy='gutenberg-catalog-public-domain-v1',license='CC0-1.0',
            retrieved_at=timezone.now())
        with TemporaryDirectory() as folder,override_settings(LITMATE_LITERARY_MEMORY_DB=Path(folder)/'memory.sqlite3'):
            remember_evidence([book],[book,bind_source(PAGE,book)])
            added=project_references([stable_work_id(book['title'],book['author'])])
            self.assertGreater(added,0)
            self.assertTrue(KBRelation.objects.filter(record=row,predicate='memory_evidence').exists())
            row.refresh_from_db()
            self.assertEqual(row.kind,'edition')
            self.assertEqual(row.payload,{'author':BOOK['author']})
            self.assertEqual(project_references([stable_work_id(book['title'],book['author'])]),0)

    def test_same_title_without_a_shared_catalogue_url_cannot_get_an_evidence_pointer(self):
        from .knowledge_models import KBRecord,KBRelation
        from .literary_identity import bind_source,stable_work_id
        from .literary_memory import remember_evidence
        from .continuous_knowledge import project_references
        KBRecord.objects.create(id='a'*64,provider='openlibrary',external_id='/works/OL999W',kind='work',
            label=BOOK['title'],payload={'author':'Otra Persona'},checksum='b'*64,status='source_metadata',
            source_url='https://openlibrary.org/works/OL999W',policy='metadata',license='CC0-1.0',
            retrieved_at=timezone.now())
        with TemporaryDirectory() as folder,override_settings(LITMATE_LITERARY_MEMORY_DB=Path(folder)/'memory.sqlite3'):
            remember_evidence([BOOK],[BOOK,bind_source(PAGE,BOOK)])
            self.assertEqual(project_references([stable_work_id(BOOK['title'],BOOK['author'])]),0)
            self.assertFalse(KBRelation.objects.exists())
