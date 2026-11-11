from django.urls import path

from . import social_posts as posts, social_profiles as profiles

urlpatterns = [
    path('comunidad/', posts.feed, name='social_feed'),
    path('comunidad/obra/<int:pk>/', posts.book, name='social_book'),
    path('lectores/<uuid:public_id>/', profiles.public_profile, name='social_public_profile'),
    path('lectores/<uuid:public_id>/lista/<int:pk>/', profiles.shared_list, name='social_shared_list'),
    path('lectores/<uuid:public_id>/imagen/<str:kind>/', profiles.profile_image, name='social_image'),
    path('lectores/<uuid:public_id>/seguir/', profiles.follow_profile, name='social_follow'),
    path('cuenta/perfil-literario/', profiles.edit_profile, name='social_edit_profile'),
    path('cuenta/compartir/<str:kind>/<int:pk>/', profiles.share_library, name='social_share_library'),
    path('cuenta/publicaciones/nueva/', posts.post_editor, name='social_new_post'),
    path('cuenta/publicaciones/<uuid:pk>/editar/', posts.post_editor, name='social_edit_post'),
    path('cuenta/publicaciones/<uuid:pk>/eliminar/', posts.delete_post, name='social_delete_post'),
    path('comunidad/publicacion/<uuid:pk>/', posts.post_detail, name='social_post'),
    path('comunidad/publicacion/<uuid:pk>/me-gusta/', posts.like_post, name='social_like'),
    path('comunidad/publicacion/<uuid:pk>/comentar/', posts.comment_post, name='social_comment'),
    path('comunidad/publicacion/<uuid:pk>/reportar/', posts.report_content, name='social_report_post'),
    path('comunidad/publicacion/<uuid:pk>/comentario/<uuid:comment_id>/eliminar/', posts.delete_comment, name='social_delete_comment'),
    path('comunidad/publicacion/<uuid:pk>/comentario/<uuid:comment_id>/reportar/', posts.report_content, name='social_report_comment'),
]
