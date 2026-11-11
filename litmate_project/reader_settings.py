"""Perfil anterior: transporte demo y cuentas compartidas."""
from .demo_settings import *  # noqa: F403
from .account_settings import apply_account_settings

apply_account_settings(globals())
