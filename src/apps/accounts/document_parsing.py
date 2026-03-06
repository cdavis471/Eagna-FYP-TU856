from __future__ import annotations

import io
import os
from html import escape
from typing import Any

import mammoth
import nh3
from bs4 import BeautifulSoup, NavigableString, Tag
from mammoth.images import img_element
from PIL import Image, UnidentifiedImageError
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER

SUPPORTED_EXTENSIONS = {".docx", ".pptx"}

SAFE_TAGS = {
    "a",
    "blockquote",
    "br",
    "em",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "img",
    "li",
    "ol",
    "p",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}

SAFE_ATTRIBUTES = {
    "a": {"href", "target", "rel"},
    "img": {"src", "alt"},
    "th": {"colspan", "rowspan"},
    "td": {"colspan", "rowspan"},
}


def validate_supported_upload(uploaded_file) -> str:
    name = getattr(uploaded_file, "name", "") or ""
    _, ext = os.path.splitext(name)
    ext = ext.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            "Only .docx and .pptx files are allowed for weekly notes and lecturer assignment materials."
        )

    return ext


def parse_uploaded_office_file(uploaded_file) -> dict[str, Any]:
    extension = validate_supported_upload(uploaded_file)

    file_bytes = uploaded_file.read()
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)

    if not file_bytes:
        raise ValueError("The uploaded file is empty.")

    if extension == ".docx":
        parsed = parse_docx_file(file_bytes)
    else:
        parsed = parse_pptx_file(file_bytes)

    parsed["extension"] = extension.lstrip(".")
    return parsed


def parse_docx_file(file_bytes: bytes) -> dict[str, Any]:
    captured_images: list[dict[str, Any]] = []
    image_counter = 0

    def convert_image(image):
        nonlocal image_counter

        image_counter += 1
        token = f"img-{image_counter}"

        extension = _extension_from_content_type(getattr(image, "content_type", "")) or "png"
        filename = f"{token}.{extension}"

        with image.open() as image_bytes:
            blob = image_bytes.read()

        blob, extension, filename = _normalise_image_blob(blob, extension, filename)

        captured_images.append(
            {
                "token": token,
                "filename": filename,
                "content": blob,
                "page_number": None,
                "alt_text": getattr(image, "alt_text", "") or "",
                "display_order": image_counter,
            }
        )

        return {
            "src": f"parsed-image:{token}",
            "alt": getattr(image, "alt_text", "") or "",
        }

    result = mammoth.convert_to_html(
        io.BytesIO(file_bytes),
        convert_image=img_element(convert_image),
        include_embedded_style_map=False,
    )

    blocks = _docx_html_to_blocks(result.value)

    return {
        "blocks": blocks,
        "page_count": len(blocks),
        "images": captured_images,
        "warnings": [str(message) for message in getattr(result, "messages", [])],
    }


def parse_pptx_file(file_bytes: bytes) -> dict[str, Any]:
    presentation = Presentation(io.BytesIO(file_bytes))

    blocks: list[dict[str, Any]] = []
    captured_images: list[dict[str, Any]] = []
    image_counter = 0

    for slide_index, slide in enumerate(presentation.slides, start=1):
        page_elements: list[dict[str, Any]] = []

        slide_title = ""
        title_shape = getattr(slide.shapes, "title", None)
        if title_shape and getattr(title_shape, "text", "").strip():
            slide_title = title_shape.text.strip()

        for shape in _sorted_shapes(slide.shapes):
            extracted_elements, image_counter, new_images = _extract_pptx_shape_content(
                shape=shape,
                slide_index=slide_index,
                image_counter=image_counter,
            )
            if extracted_elements:
                page_elements.extend(extracted_elements)
            if new_images:
                captured_images.extend(new_images)

        if not page_elements:
            continue

        blocks.append(
            {
                "type": "page",
                "page_number": slide_index,
                "label": slide_title or f"Slide {slide_index}",
                "elements": page_elements,
            }
        )

    return {
        "blocks": blocks,
        "page_count": len(blocks),
        "images": captured_images,
        "warnings": [],
    }


def build_rendered_html_from_blocks(
    blocks: list[dict[str, Any]],
    image_lookup: dict[str, dict[str, str]],
) -> str:
    page_html: list[str] = []
    total_pages = len(blocks)

    for index, page in enumerate(blocks, start=1):
        label = escape(str(page.get("label") or f"Page {index}"))
        inner_html: list[str] = []

        for element in page.get("elements", []):
            if element.get("type") != "raw_html":
                continue

            snippet = _hydrate_image_placeholders(
                element.get("html", ""),
                image_lookup=image_lookup,
            )
            snippet = _sanitize_user_html(snippet)

            if "<table" in snippet:
                snippet = f'<div class="parsed-table-wrap">{snippet}</div>'

            inner_html.append(snippet)

        page_html.append(
            f'<section class="parsed-page" aria-label="{label}">'
            f'<div class="parsed-page-header">{label}</div>'
            f'{"".join(inner_html)}'
            f"</section>"
        )

        if index < total_pages:
            page_html.append('<hr class="parsed-page-break" aria-hidden="true">')

    return "".join(page_html)


def _docx_html_to_blocks(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    body_nodes: list[Tag] = []

    for child in soup.contents:
        if isinstance(child, NavigableString):
            if child.strip():
                frag = BeautifulSoup(f"<p>{escape(str(child).strip())}</p>", "html.parser")
                if frag.p:
                    body_nodes.append(frag.p)
            continue

        if isinstance(child, Tag):
            body_nodes.append(child)

    pages: list[dict[str, Any]] = []
    current_page = {
        "type": "page",
        "page_number": 1,
        "label": "Page 1",
        "elements": [],
    }

    for node in body_nodes:
        if node.name in {"h1", "h2"} and current_page["elements"]:
            pages.append(current_page)
            next_number = len(pages) + 1
            current_page = {
                "type": "page",
                "page_number": next_number,
                "label": f"Page {next_number}",
                "elements": [],
            }

        snippet = str(node)
        if snippet.strip():
            current_page["elements"].append(
                {
                    "type": "raw_html",
                    "html": snippet,
                }
            )

    if current_page["elements"]:
        pages.append(current_page)

    if not pages:
        pages.append(
            {
                "type": "page",
                "page_number": 1,
                "label": "Page 1",
                "elements": [
                    {
                        "type": "raw_html",
                        "html": "<p>No readable content could be extracted from this document.</p>",
                    }
                ],
            }
        )

    return pages


def _sorted_shapes(shapes) -> list[Any]:
    ordered: list[Any] = []

    for shape in shapes:
        if getattr(shape, "shape_type", None) == MSO_SHAPE_TYPE.GROUP:
            ordered.extend(_sorted_shapes(shape.shapes))
        else:
            ordered.append(shape)

    return sorted(ordered, key=lambda shp: (getattr(shp, "top", 0), getattr(shp, "left", 0)))


def _extract_pptx_shape_content(shape, slide_index: int, image_counter: int):
    elements: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []

    shape_type = getattr(shape, "shape_type", None)

    if shape_type == MSO_SHAPE_TYPE.PICTURE:
        image_counter += 1
        token = f"img-{image_counter}"

        img = shape.image
        extension = (getattr(img, "ext", "") or "png").lower()
        filename = getattr(img, "filename", "") or f"{token}.{extension}"
        blob = img.blob

        blob, extension, filename = _normalise_image_blob(blob, extension, filename)
        alt_text = _best_picture_alt_text(shape, slide_index)

        images.append(
            {
                "token": token,
                "filename": filename,
                "content": blob,
                "page_number": slide_index,
                "alt_text": alt_text,
                "display_order": image_counter,
            }
        )

        elements.append(
            {
                "type": "raw_html",
                "html": (
                    f'<figure><img src="parsed-image:{token}" alt="{escape(alt_text)}"></figure>'
                ),
            }
        )
        return elements, image_counter, images

    if getattr(shape, "has_table", False):
        table_html = _table_to_html(shape.table)
        if table_html:
            elements.append({"type": "raw_html", "html": table_html})
        return elements, image_counter, images

    if getattr(shape, "has_text_frame", False):
        text_html = _text_frame_to_html(shape)
        if text_html:
            elements.append({"type": "raw_html", "html": text_html})
        return elements, image_counter, images

    return elements, image_counter, images


def _text_frame_to_html(shape) -> str:
    text_frame = shape.text_frame
    paragraphs = [p for p in text_frame.paragraphs if (p.text or "").strip()]

    if not paragraphs:
        return ""

    placeholder_type = None
    if getattr(shape, "is_placeholder", False):
        try:
            placeholder_type = shape.placeholder_format.type
        except Exception:
            placeholder_type = None

    html_parts: list[str] = []

    if placeholder_type in {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}:
        html_parts.append(f"<h2>{_paragraph_inline_html(paragraphs[0])}</h2>")
        paragraphs = paragraphs[1:]
    elif placeholder_type == PP_PLACEHOLDER.SUBTITLE:
        html_parts.append(f"<h3>{_paragraph_inline_html(paragraphs[0])}</h3>")
        paragraphs = paragraphs[1:]

    if not paragraphs:
        return "".join(html_parts)

    should_render_as_list = (
        placeholder_type in {PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT}
        and len(paragraphs) > 1
    )

    if should_render_as_list:
        html_parts.append("<ul>")
        for paragraph in paragraphs:
            html_parts.append(f"<li>{_paragraph_inline_html(paragraph)}</li>")
        html_parts.append("</ul>")
    else:
        for paragraph in paragraphs:
            html_parts.append(f"<p>{_paragraph_inline_html(paragraph)}</p>")

    return "".join(html_parts)


def _paragraph_inline_html(paragraph) -> str:
    fragments: list[str] = []
    runs = list(getattr(paragraph, "runs", []))

    if not runs:
        return escape((paragraph.text or "").strip())

    for run in runs:
        text = escape(run.text or "")
        if not text:
            continue

        href = getattr(getattr(run, "hyperlink", None), "address", None)
        if href:
            text = (
                f'<a href="{escape(href, quote=True)}" '
                f'target="_blank" rel="noopener noreferrer">{text}</a>'
            )

        if getattr(getattr(run, "font", None), "bold", False):
            text = f"<strong>{text}</strong>"

        if getattr(getattr(run, "font", None), "italic", False):
            text = f"<em>{text}</em>"

        fragments.append(text)

    return "".join(fragments).strip()


def _table_to_html(table) -> str:
    rows_html: list[str] = []

    for row_index, row in enumerate(table.rows):
        cell_tag = "th" if row_index == 0 else "td"
        cell_html: list[str] = []

        for cell in row.cells:
            text = escape(cell.text.strip()) if cell.text else ""
            cell_html.append(f"<{cell_tag}>{text}</{cell_tag}>")

        rows_html.append(f"<tr>{''.join(cell_html)}</tr>")

    if not rows_html:
        return ""

    return f"<table><tbody>{''.join(rows_html)}</tbody></table>"


def _hydrate_image_placeholders(
    snippet: str,
    image_lookup: dict[str, dict[str, str]],
) -> str:
    soup = BeautifulSoup(snippet or "", "html.parser")

    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()

        if not src.startswith("parsed-image:"):
            continue

        token = src.split("parsed-image:", 1)[1]
        data = image_lookup.get(token)

        if not data:
            img.decompose()
            continue

        img["src"] = data["src"]
        img["alt"] = data.get("alt_text", "") or img.get("alt", "") or ""

    return str(soup)


def _sanitize_user_html(html: str) -> str:
    return nh3.clean(
        html or "",
        tags=SAFE_TAGS,
        attributes=SAFE_ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
    )


def _best_picture_alt_text(shape, slide_index: int) -> str:
    try:
        descr = shape._element.xpath(
            ".//p:cNvPr/@descr",
            namespaces={"p": "http://schemas.openxmlformats.org/presentationml/2006/main"},
        )
        if descr and descr[0].strip():
            return descr[0].strip()
    except Exception:
        pass

    return f"Image from slide {slide_index}"


def _extension_from_content_type(content_type: str) -> str:
    mapping = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/gif": "gif",
        "image/svg+xml": "svg",
        "image/webp": "webp",
        "image/tiff": "tiff",
        "image/bmp": "bmp",
        "image/x-emf": "emf",
        "image/x-wmf": "wmf",
    }
    return mapping.get((content_type or "").lower(), "png")


def _normalise_image_blob(blob: bytes, extension: str, filename: str):
    extension = (extension or "png").lower()

    if extension in {"emf", "wmf"}:
        return blob, extension, filename

    try:
        with Image.open(io.BytesIO(blob)) as img:
            output = io.BytesIO()

            save_format = "PNG" if img.mode in {"RGBA", "LA", "P"} else "JPEG"
            converted = img.convert("RGBA" if save_format == "PNG" else "RGB")
            converted.save(output, format=save_format)

            new_extension = "png" if save_format == "PNG" else "jpg"
            root, _ = os.path.splitext(filename)
            return output.getvalue(), new_extension, f"{root}.{new_extension}"

    except (UnidentifiedImageError, OSError):
        return blob, extension, filename