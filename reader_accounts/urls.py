"""Perfil anterior: mismas cuentas y p?ginas de demostraci?n."""
from django.urls import path, include
from .account_urls import urlpatterns as account_patterns

urlpatterns = [*account_patterns, path('', include('litmate_project.demo_urls'))]
