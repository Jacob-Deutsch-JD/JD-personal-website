import json
import re
from pathlib import Path
from PIL import Image, ImageOps

# Expected structure:
# photography/
#   build_gallery.py
#   photography.html
#   images.js
#   gallery/
#     001_darkling_beetle/
#       1.jpg
#       2.jpg
#       post.xml
#       post.json
#       thumbs/
#         1.webp
#         2.webp
#
# post.xml is treated as raw HTML-ish text. It is NOT parsed as XML.
# Whatever you write in post.xml is inserted into the opened post page below the photos.
#
# Example post.xml:
#   <h2><em>Eleodes</em> darkling beetle</h2>
#   <p>This is a <a href="https://example.com">darkling beetle</a>.</p>
#
# post.json controls non-visible metadata / display settings.
#
# Example post.json:
#   {
#     "accessibilityLabel": "Eleodes darkling beetle",
#     "backgroundColor": "#111111"
#   }
#
# accessibilityLabel is used for alt text, aria-labels, and keyboard/screen-reader context.
# It is not visibly displayed by photography.html.
#
# backgroundColor accepts #abc or #aabbcc.

SCRIPT_DIR = Path(__file__).resolve().parent
IMAGE_FOLDER = SCRIPT_DIR / "gallery"
OUTPUT_FILE = SCRIPT_DIR / "images.js"

VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
POST_XML_FILENAME = "post.xml"
POST_CONFIG_FILENAME = "post.json"
THUMB_SUBFOLDER_NAME = "thumbs"

# Long edge for thumbnails. 500-700 is a good range.
THUMB_MAX_SIZE = 600

# WebP is usually much smaller than jpg/png for thumbnails.
THUMB_FORMAT = "WEBP"
THUMB_EXTENSION = ".webp"
WEBP_QUALITY = 80

DEFAULT_BACKGROUND_COLOR = "#111111"

HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def natural_sort_key(path):
    """Sort 1.jpg, 2.jpg, 10.jpg in human order instead of 1, 10, 2."""
    parts = re.split(r"(\d+)", path.name.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def slug_to_label(slug):
    """Fallback only: turn '001_blewett_pass' into 'Blewett Pass'."""
    cleaned = re.sub(r"^\d+[-_ ]*", "", slug)
    cleaned = cleaned.replace("-", " ").replace("_", " ").strip()
    return cleaned.title() if cleaned else slug


def clean_hex_color(value, fallback=DEFAULT_BACKGROUND_COLOR):
    """Accept #abc or #aabbcc. Anything else falls back safely."""
    if not isinstance(value, str):
        return fallback

    value = value.strip()
    if HEX_COLOR_RE.match(value):
        return value

    print("Warning: invalid backgroundColor {!r}; using {}".format(value, fallback))
    return fallback


def read_post_config(post_folder):
    config_path = post_folder / POST_CONFIG_FILENAME

    config = {
        "accessibilityLabel": slug_to_label(post_folder.name),
        "backgroundColor": DEFAULT_BACKGROUND_COLOR,
    }

    if not config_path.exists():
        return config

    try:
        raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit("Could not parse {}: {}".format(config_path, exc))

    if not isinstance(raw_config, dict):
        raise SystemExit(
            "{} must contain a JSON object like {{\"accessibilityLabel\": \"...\", \"backgroundColor\": \"#111111\"}}.".format(
                config_path
            )
        )

    accessibility_label = raw_config.get("accessibilityLabel")
    if isinstance(accessibility_label, str) and accessibility_label.strip():
        config["accessibilityLabel"] = accessibility_label.strip()

    config["backgroundColor"] = clean_hex_color(
        raw_config.get("backgroundColor", DEFAULT_BACKGROUND_COLOR)
    )

    return config


def read_post_markup(post_folder):
    post_xml_path = post_folder / POST_XML_FILENAME
    if not post_xml_path.exists():
        return ""
    return post_xml_path.read_text(encoding="utf-8").strip()


def read_post_metadata(post_folder):
    config = read_post_config(post_folder)
    post_markup = read_post_markup(post_folder)

    return {
        "accessibilityLabel": config["accessibilityLabel"],
        "postHtml": post_markup,
        "backgroundColor": config["backgroundColor"],
        "metadataFile": POST_XML_FILENAME if post_markup else None,
        "configFile": POST_CONFIG_FILENAME if (post_folder / POST_CONFIG_FILENAME).exists() else None,
    }


def ensure_thumbnail(src_path, thumb_path):
    thumb_path.parent.mkdir(parents=True, exist_ok=True)

    # Only regenerate if missing or original is newer.
    if thumb_path.exists() and src_path.stat().st_mtime <= thumb_path.stat().st_mtime:
        return

    with Image.open(src_path) as im:
        # Respect EXIF orientation.
        im = ImageOps.exif_transpose(im)

        thumb = im.copy()
        thumb.thumbnail((THUMB_MAX_SIZE, THUMB_MAX_SIZE))

        thumb.save(
            thumb_path,
            THUMB_FORMAT,
            quality=WEBP_QUALITY,
            method=6,
        )


def path_for_web(path):
    """Return a path relative to photography.html/images.js, using web slashes."""
    return path.relative_to(SCRIPT_DIR).as_posix()


def build_gallery_posts():
    posts = []

    post_folders = [
        item
        for item in IMAGE_FOLDER.iterdir()
        if item.is_dir() and not item.name.startswith(".")
    ]

    for post_folder in sorted(post_folders, key=natural_sort_key):
        thumb_folder = post_folder / THUMB_SUBFOLDER_NAME

        image_paths = sorted(
            [
                item
                for item in post_folder.iterdir()
                if item.is_file()
                and not item.name.startswith(".")
                and item.suffix.lower() in VALID_EXTENSIONS
            ],
            key=natural_sort_key,
        )

        if not image_paths:
            continue

        metadata = read_post_metadata(post_folder)
        slug = post_folder.name
        images = []

        for src_path in image_paths:
            thumb_name = src_path.stem + THUMB_EXTENSION
            thumb_path = thumb_folder / thumb_name
            ensure_thumbnail(src_path, thumb_path)

            images.append(
                {
                    "thumb": path_for_web(thumb_path),
                    "full": path_for_web(src_path),
                    "filename": src_path.name,
                }
            )

        posts.append(
            {
                "slug": slug,
                "accessibilityLabel": metadata["accessibilityLabel"],
                "postHtml": metadata["postHtml"],
                "backgroundColor": metadata["backgroundColor"],
                "metadataFile": metadata["metadataFile"],
                "configFile": metadata["configFile"],
                "cover": images[0],
                "images": images,
            }
        )

    return posts


def write_images_js(posts):
    js = "window.galleryPosts = " + json.dumps(posts, ensure_ascii=False, indent=2) + ";\n"
    OUTPUT_FILE.write_text(js, encoding="utf-8")


def main():
    if not IMAGE_FOLDER.exists():
        raise SystemExit("Missing gallery folder: {}".format(IMAGE_FOLDER))

    posts = build_gallery_posts()
    write_images_js(posts)

    image_count = sum(len(post["images"]) for post in posts)
    print("Wrote {} posts / {} images to {}".format(len(posts), image_count, OUTPUT_FILE))
    print("Thumbnails stored inside each post folder as '{}/'".format(THUMB_SUBFOLDER_NAME))


if __name__ == "__main__":
    main()
