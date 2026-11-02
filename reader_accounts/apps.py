from django.apps import AppConfig


class ReaderAccountsConfig(AppConfig):
    name = 'reader_accounts'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        from django.db.backends.signals import connection_created
        from .router import protect_catalogue
        connection_created.connect(protect_catalogue,weak=False,dispatch_uid='reader-catalogue-readonly')
