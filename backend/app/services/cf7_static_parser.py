"""Bounded inert HTML inspection. Standalone subprocess; no app/network imports."""

import json
import re
import sys
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

LIMIT = 262144
MARKERS = {"_wpcf7", "_wpcf7_version", "_wpcf7_locale", "_wpcf7_unit_tag"}


class Inspector(HTMLParser):
    def __init__(self, url: str, index: int):
        super().__init__(convert_charrefs=True)
        self.url = url
        self.index = index
        self.forms: list[dict] = []
        self.current: dict | None = None
        self.tags = 0
        self.rest_same_origin = False
        self.base_override = False

    def handle_starttag(self, tag, attributes):
        self.tags += 1
        if self.tags > 10000:
            raise ValueError("tag limit")
        attrs = dict(attributes)
        if len(attrs) != len(attributes):
            raise ValueError("duplicate attribute")
        if tag == "base":
            self.base_override = True
        if tag == "link" and "https://api.w.org/" in (attrs.get("rel") or "").split():
            root = urlsplit(urljoin(self.url, attrs.get("href") or ""))
            source = urlsplit(self.url)
            self.rest_same_origin = (
                root.scheme == source.scheme == "https"
                and root.netloc == source.netloc
                and not root.username
                and not root.password
                and not root.query
                and not root.fragment
                and root.path.endswith("/wp-json/")
            )
        if tag == "form":
            if self.current is not None:
                raise ValueError("nested form")
            self.current = {
                "marker": "wpcf7-form" in (attrs.get("class") or "").split(),
                "post": (attrs.get("method") or "get").lower() == "post",
                "enctype": (attrs.get("enctype") or "application/x-www-form-urlencoded").lower()
                in {"application/x-www-form-urlencoded", "multipart/form-data"},
                "names": [],
                "markers": set(),
                "version": None,
                "id_valid": False,
                "missing": 0,
                "files": 0,
                "unsupported": 0,
            }
            self.forms.append(self.current)
            if len(self.forms) > 20:
                raise ValueError("form limit")
        if self.current is None or tag not in {"input", "textarea", "select", "button"}:
            return
        kind = (attrs.get("type") or "text").lower() if tag == "input" else tag
        name = attrs.get("name") or ""
        if len(name) > 100:
            raise ValueError("name limit")
        if name:
            self.current["names"].append(name)
        elif kind not in {"hidden", "submit", "button", "reset", "image"}:
            self.current["missing"] += 1
        if name in MARKERS:
            self.current["marker"] = True
            if name in self.current["markers"]:
                raise ValueError("duplicate marker")
            if kind == "hidden":
                self.current["markers"].add(name)
        if name == "_wpcf7_version" and kind == "hidden":
            version = attrs.get("value") or ""
            if re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,3}){1,3}", version):
                self.current["version"] = version
        if name == "_wpcf7" and kind == "hidden":
            self.current["id_valid"] = bool(
                re.fullmatch(r"[1-9][0-9]{0,9}", attrs.get("value") or "")
            )
        self.current["files"] += kind == "file"
        self.current["unsupported"] += kind not in {
            "text",
            "email",
            "tel",
            "textarea",
            "checkbox",
            "radio",
            "select",
            "hidden",
            "submit",
            "button",
            "reset",
        }
        if len(self.current["names"]) > 100:
            raise ValueError("control limit")

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)


def inspect_html(html: str, url: str, index: int) -> dict:
    if len(html.encode("utf-8")) > LIMIT or type(index) is not int or not 0 <= index < 20:
        raise ValueError("input limit")
    parser = Inspector(url, index)
    parser.feed(html)
    parser.close()
    if parser.current is not None:
        raise ValueError("unclosed form")
    form = parser.forms[index] if index < len(parser.forms) else None
    return {
        "status": "FORM_MISSING"
        if form is None
        else "CF7_CANDIDATE"
        if form["marker"]
        else "NOT_CF7",
        "form_count": len(parser.forms),
        "version": form["version"] if form else None,
        "form_id_valid": bool(form and form["id_valid"]),
        "markers_complete": bool(form and form["markers"] == MARKERS),
        "method_is_post": bool(form and form["post"]),
        "enctype_supported": bool(form and form["enctype"]),
        "missing_names": form["missing"] if form else 0,
        "file_inputs": form["files"] if form else 0,
        "unsupported_controls": form["unsupported"] if form else 0,
        "rest_link_same_origin": parser.rest_same_origin and not parser.base_override,
        "base_override": parser.base_override,
        "execution_allowed": False,
        "eligible_for_approval": False,
    }


if __name__ == "__main__":
    try:
        raw = sys.stdin.buffer.read(LIMIT * 2 + 1)
        if len(raw) > LIMIT * 2:
            raise ValueError("input limit")
        data = json.loads(raw)
        result = inspect_html(data["html"], data["url"], data["index"])
        print(json.dumps(result, ensure_ascii=True))
    except Exception:
        print('{"status":"PARSE_FAILED"}')
