"""Datos sociales en la base de cuentas. Las referencias al catálogo son escalares."""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class SocialProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='social_profile')
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    alias = models.CharField(max_length=32, blank=True)
    display_name = models.CharField(max_length=80, blank=True)
    biography = models.CharField(max_length=480, blank=True)
    genres = models.CharField(max_length=120, blank=True)
    favorite_author = models.CharField(max_length=100, blank=True)
    favorite_book = models.CharField(max_length=150, blank=True)
    published = models.BooleanField(default=False)
    share_avatar = models.BooleanField(default=False)
    share_cover = models.BooleanField(default=False)
    share_stats = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['alias'], condition=~Q(alias=''), name='social_unique_alias'),
        ]

    @property
    def name(self):
        return self.display_name or self.alias or 'Lector'


class ProfileCover(models.Model):
    profile = models.OneToOneField(SocialProfile, on_delete=models.CASCADE, related_name='cover')
    jpeg = models.BinaryField(editable=False)


class Follow(models.Model):
    follower = models.ForeignKey(SocialProfile, on_delete=models.CASCADE, related_name='following')
    target = models.ForeignKey(SocialProfile, on_delete=models.CASCADE, related_name='followers')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['follower', 'target'], name='social_unique_follow'),
            models.CheckConstraint(condition=~Q(follower=F('target')), name='social_no_self_follow'),
        ]


class SocialPost(models.Model):
    class Visibility(models.TextChoices):
        PRIVATE = 'private', 'Privado'
        FOLLOWERS = 'followers', 'Solo seguidores'
        PUBLIC = 'public', 'Público'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(SocialProfile, on_delete=models.CASCADE, related_name='posts')
    submission_id = models.UUIDField(editable=False)
    body = models.CharField(max_length=2400)
    catalogue_id = models.PositiveBigIntegerField(null=True, blank=True)
    visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.PRIVATE)
    spoiler = models.BooleanField(default=False)
    allow_comments = models.BooleanField(default=True)
    moderated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['visibility', '-created_at'], name='social_post_visibility')]
        constraints = [
            models.UniqueConstraint(fields=['author', 'submission_id'], name='social_unique_post_submission'),
        ]


class PostLike(models.Model):
    post = models.ForeignKey(SocialPost, on_delete=models.CASCADE, related_name='likes')
    author = models.ForeignKey(SocialProfile, on_delete=models.CASCADE, related_name='likes')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['post', 'author'], name='social_unique_like')]


class SocialComment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(SocialPost, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(SocialProfile, on_delete=models.CASCADE, related_name='comments')
    submission_id = models.UUIDField(editable=False)
    body = models.CharField(max_length=600)
    moderated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']
        constraints = [
            models.UniqueConstraint(fields=['post', 'author', 'submission_id'], name='social_unique_comment_submission'),
        ]


class SocialReport(models.Model):
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    post = models.ForeignKey(SocialPost, on_delete=models.CASCADE, null=True, blank=True)
    comment = models.ForeignKey(SocialComment, on_delete=models.CASCADE, null=True, blank=True)
    reason = models.CharField(max_length=400)
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(Q(post__isnull=False, comment__isnull=True) | Q(post__isnull=True, comment__isnull=False)),
                name='social_report_exact_target',
            ),
            models.UniqueConstraint(fields=['reporter', 'post'], name='social_unique_post_report'),
            models.UniqueConstraint(fields=['reporter', 'comment'], name='social_unique_comment_report'),
        ]


class SharedReading(models.Model):
    item = models.OneToOneField('core.ElementoListaLectura', on_delete=models.CASCADE, related_name='social_share')
    created_at = models.DateTimeField(auto_now_add=True)


class SharedList(models.Model):
    reading_list = models.OneToOneField('core.ListaLectura', on_delete=models.CASCADE, related_name='social_share')
    created_at = models.DateTimeField(auto_now_add=True)


class AnnualReading(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    book_id = models.CharField(max_length=100)
    year = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'year', 'book_id'], name='social_unique_annual_book')]
