import os
from pathlib import Path
from PIL import Image, ImageOps

IMAGE_FOLDER = Path("gallery")
THUMB_FOLDER = IMAGE_FOLDER / "thumbs"
OUTPUT_FILE = Path("images.js")

VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# Long edge for thumbnails. 500-700 is a good range.
THUMB_MAX_SIZE = 600

# WebP is usually much smaller than jpg/png for thumbnails.
THUMB_FORMAT = "WEBP"
THUMB_EXTENSION = ".webp"
WEBP_QUALITY = 80

THUMB_FOLDER.mkdir(exist_ok=True)

entries = []

for filename in sorted(os.listdir(IMAGE_FOLDER)):
    src_path = IMAGE_FOLDER / filename

    if not src_path.is_file():
        continue

    ext = src_path.suffix.lower()
    if ext not in VALID_EXTENSIONS:
        continue

    thumb_name = src_path.stem + THUMB_EXTENSION
    thumb_path = THUMB_FOLDER / thumb_name

    # Only regenerate if missing or original is newer
    if (not thumb_path.exists()) or (src_path.stat().st_mtime > thumb_path.stat().st_mtime):
        with Image.open(src_path) as im:
            # Respect EXIF orientation
            im = ImageOps.exif_transpose(im)

            # Make a copy and shrink it
            thumb = im.copy()
            thumb.thumbnail((THUMB_MAX_SIZE, THUMB_MAX_SIZE))

            # Save as WebP thumbnail
            thumb.save(
                thumb_path,
                THUMB_FORMAT,
                quality=WEBP_QUALITY,
                method=6
            )

    entries.append({
        "thumb": f"gallery/thumbs/{thumb_name}",
        "full": f"gallery/{filename}"
    })

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write("window.galleryImages = [\n")
    for i, item in enumerate(entries):
        comma = "," if i < len(entries) - 1 else ""
        f.write(
            f'  {{ thumb: "{item["thumb"]}", full: "{item["full"]}" }}{comma}\n'
        )
    f.write("];\n")

print(f"Wrote {len(entries)} image entries to {OUTPUT_FILE}")
print(f"Thumbnails stored in {THUMB_FOLDER}")