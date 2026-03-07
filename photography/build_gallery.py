import os

IMAGE_FOLDER = "gallery"
OUTPUT_FILE = "images.js"
VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

files = []

for filename in sorted(os.listdir(IMAGE_FOLDER)):
    ext = os.path.splitext(filename)[1].lower()
    if ext in VALID_EXTENSIONS:
        files.append(f"{IMAGE_FOLDER}/{filename}")

with open(OUTPUT_FILE, "w") as f:
    f.write("window.galleryImages = [\n")
    for i, path in enumerate(files):
        comma = "," if i < len(files) - 1 else ""
        f.write(f'  "{path}"{comma}\n')
    f.write("];\n")

print(f"Wrote {len(files)} image paths to {OUTPUT_FILE}")