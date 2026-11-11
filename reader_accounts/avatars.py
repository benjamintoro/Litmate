"""Avatares privados normalizados; nunca sirven archivos elegidos por una URL."""
from io import BytesIO
from pathlib import Path
import re
import secrets
from django.conf import settings
from django.core.exceptions import ValidationError
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD = 2 * 1024 * 1024
MAX_PIXELS = 4_000_000


def normalize(upload, *, cover=False, square=False, centering=(.5, .5)):
    if upload.size > MAX_UPLOAD:
        raise ValidationError('La imagen no puede superar 2 MiB.')
    raw = upload.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise ValidationError('La imagen no puede superar 2 MiB.')
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format not in ('JPEG', 'PNG') or image.width * image.height > MAX_PIXELS:
                raise ValueError('unsupported image')
            image.verify()
        with Image.open(BytesIO(raw)) as image:
            image = ImageOps.exif_transpose(image)
            if cover:
                if image.width < 640 or image.height < 210:
                    raise ValidationError('La portada debe medir al menos 640 × 210 píxeles.')
                image = ImageOps.fit(image, (1280, 420), method=Image.Resampling.LANCZOS, centering=centering)
            elif square:
                if min(image.size) < 64:
                    raise ValidationError('La fotografía debe medir al menos 64 × 64 píxeles.')
                image = ImageOps.fit(image, (256, 256), method=Image.Resampling.LANCZOS)
            else:
                image.thumbnail((256, 256))
            if image.mode in ('RGBA', 'LA') or 'transparency' in image.info:
                rgba = image.convert('RGBA')
                normalized = Image.new('RGB', rgba.size, 'white')
                normalized.paste(rgba, mask=rgba.getchannel('A'))
            else:
                normalized = image.convert('RGB')
            normalized.info.clear()
            output = BytesIO()
            # No copia EXIF, comentarios, perfiles ICC ni el nombre original.
            normalized.save(output, format='JPEG', quality=82 if cover else 85, optimize=cover)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise ValidationError('Utiliza una imagen JPEG o PNG válida de hasta 4 megapíxeles.') from error


def private_root():
    root = Path(settings.LITMATE_AVATAR_ROOT).resolve()
    base = Path(settings.BASE_DIR).resolve()
    if not any(root.is_relative_to(parent) for parent in (base/'data/accounts', base/'.testtmp')):
        raise ValueError('El almacenamiento de imágenes debe ser privado.')
    return root


def store(content):
    root = private_root()
    root.mkdir(parents=True, exist_ok=True)
    name = secrets.token_hex(16) + '.jpg'
    with (root/name).open('xb') as stream:
        stream.write(content)
    # Se conserva el campo de core.PerfilUsuario, sin otro modelo de fotos.
    return 'avatars/' + name


def own_path(value):
    if not re.fullmatch(r'avatars/[a-f0-9]{32}\.jpg', value):
        return None
    root = private_root()
    path = root/value.split('/')[1]
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 128 * 1024:
        return None
    return path
