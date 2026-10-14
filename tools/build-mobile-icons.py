"""Rasterize the simple code-native flower mark for PWA installation."""
from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1] / 'mobile' / 'static'
for size in (192, 512):
    image = Image.new('RGB', (512, 512), '#faf7ff')
    draw = ImageDraw.Draw(image)
    for box in [(201, 73, 311, 283), (201, 229, 311, 439), (73, 201, 283, 311), (229, 201, 439, 311)]:
        draw.ellipse(box, fill='#ad8bca')
    draw.ellipse((194, 194, 318, 318), fill='#8866af')
    draw.ellipse((229, 229, 283, 283), fill='white')
    image.resize((size, size), Image.Resampling.LANCZOS).save(root / f'icon-{size}.png')
