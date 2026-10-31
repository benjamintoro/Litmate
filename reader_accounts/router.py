"""Ninguna escritura de cuentas llega al catálogo MySQL protegido."""
ACCOUNT_CORE = {'perfilusuario', 'asistenteia', 'conversacionia', 'mensajeia', 'historialchatbot'}


def is_account(app, model):
    return app in {'reader_accounts', 'auth', 'contenttypes', 'sessions', 'suscripciones'} or (
        app == 'core' and model in ACCOUNT_CORE)


def protect_catalogue(sender,connection,**kwargs):
    if connection.alias == 'default' and connection.vendor == 'mysql':
        with connection.cursor() as cursor:
            cursor.execute('SET SESSION TRANSACTION READ ONLY')


class AccountsRouter:
    def db_for_read(self, model, **hints):
        return 'accounts' if is_account(model._meta.app_label, model._meta.model_name) else 'default'

    db_for_write = db_for_read

    def allow_relation(self, obj1, obj2, **hints):
        first = is_account(obj1._meta.app_label, obj1._meta.model_name)
        second = is_account(obj2._meta.app_label, obj2._meta.model_name)
        return first == second

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if db == 'accounts':
            return is_account(app_label, model_name)
        # En este perfil jamás se migra el catálogo original, ni accidentalmente.
        return False
