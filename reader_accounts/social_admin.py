"""La revisión se limita a contenido reportado mediante la comunidad."""
from django.conf import settings
from django.contrib import admin
from django.db import transaction

from .models import SocialComment, SocialPost


class SocialReportAdmin(admin.ModelAdmin):
    list_display = ('pk', 'created_at', 'resolved')
    list_filter = ('resolved',)
    fields = ('reason', 'reported_text', 'created_at', 'resolved')
    readonly_fields = fields
    list_select_related = ('post__author', 'comment__post__author', 'comment__author')
    actions = ('withdraw_content', 'resolve_reports')

    def has_module_permission(self, request):
        return settings.LITMATE_COMMUNITY_ENABLED and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return settings.LITMATE_COMMUNITY_ENABLED and super().has_view_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return settings.LITMATE_COMMUNITY_ENABLED and super().has_change_permission(request, obj)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='Texto reportado')
    def reported_text(self, report):
        post = report.post if report.post_id else report.comment.post
        if post.visibility == SocialPost.Visibility.PRIVATE or not post.author.published:
            return 'El contenido pasó a ser privado.'
        if report.comment_id and (not post.allow_comments or not report.comment.author.published):
            return 'El comentario dejó de estar disponible.'
        return (report.comment if report.comment_id else post).body

    @admin.action(description='Retirar contenido reportado y cerrar reportes', permissions=['change'])
    def withdraw_content(self, request, queryset):
        with transaction.atomic(using='accounts'):
            post_ids = queryset.exclude(post_id=None).values('post_id')
            comment_ids = queryset.exclude(comment_id=None).values('comment_id')
            SocialPost.objects.filter(pk__in=post_ids).update(moderated=True)
            SocialComment.objects.filter(pk__in=comment_ids).update(moderated=True)
            count = queryset.update(resolved=True)
        self.message_user(request, f'Reportes cerrados: {count}.')

    @admin.action(description='Cerrar reportes revisados', permissions=['change'])
    def resolve_reports(self, request, queryset):
        count = queryset.update(resolved=True)
        self.message_user(request, f'Reportes cerrados: {count}.')
