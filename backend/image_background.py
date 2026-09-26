"""Shared paper-white compositing, independent of modules cached by a running server."""
from PIL import Image

def opaque_rgb(image):
    """Flatten transparency on paper-white, preserving dark ink and fine lines."""
    if image.mode in ['RGBA','LA'] or 'transparency' in image.info:
        rgba=image.convert('RGBA')
        background=Image.new('RGBA',rgba.size,(255,255,255,255))
        return Image.alpha_composite(background,rgba).convert('RGB')
    return image.convert('RGB')
