"""Bounded inert HTML inspection. Standalone subprocess; no app/network imports."""

import json
import re
import sys
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

LIMIT = 262144
CONTRACT_MARKERS = {
    "_wpcf7",
    "_wpcf7_version",
    "_wpcf7_locale",
    "_wpcf7_unit_tag",
    "_wpcf7_container_post",
    "_wpcf7_posted_data_hash",
}
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
        self.scripts: list[str] = []
        self.script: str | None = None
        self.external_control = False

    def handle_starttag(self, tag, attributes):
        self.tags += 1
        if self.tags > 10000:
            raise ValueError("tag limit")
        attrs = dict(attributes)
        if len(attrs) != len(attributes):
            raise ValueError("duplicate attribute")
        if tag == "script":
            self.script = ""
        if "form" in attrs:
            self.external_control = True
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
                "hidden": {},
                "visible_names": [],
                "radios": 0,
                "selects": 0,
                "checkboxes": 0,
                "checked": 0,
                "disabled": 0,
                "markers": set(),
                "version": None,
                "id_valid": False,
                "missing": 0,
                "files": 0,
                "unsupported": 0,
                "controls": [],
                "order": [],
                "custom": any(k.startswith("on") for k in attrs),
            }
            self.forms.append(self.current)
            if len(self.forms) > 20:
                raise ValueError("form limit")
        if self.current is not None:
            self.current["custom"] |= (
                any(k.startswith("on") for k in attrs) or tag == "fieldset" and "disabled" in attrs
            )
            # Acceptance has wrapper-dependent/inverted semantics; defer rather than infer.
            self.current["custom"] |= "wpcf7-acceptance" in (attrs.get("class") or "").split()
        if self.current is None or tag not in {"input", "textarea", "select", "button"}:
            return
        kind = (attrs.get("type") or "text").lower() if tag == "input" else tag
        self.current["custom"] |= any(
            k.startswith("on")
            or k
            in {
                "formaction",
                "formmethod",
                "pattern",
                "min",
                "max",
                "minlength",
                "maxlength",
                "multiple",
            }
            for k in attrs
        )
        name = attrs.get("name") or ""
        if len(name) > 100:
            raise ValueError("name limit")
        if name:
            self.current["names"].append(name)
        elif kind not in {"hidden", "submit", "button", "reset", "image"}:
            self.current["missing"] += 1
        if kind == "hidden":
            if name in self.current["hidden"]:
                raise ValueError("duplicate hidden")
            self.current["hidden"][name] = attrs.get("value") or ""
            self.current["order"].append(name)
        elif kind not in {"submit", "button", "reset", "image"}:
            self.current["visible_names"].append(name)
            self.current["disabled"] += "disabled" in attrs
            self.current["order"].append(name)
            self.current["controls"].append(
                {
                    "name": name,
                    "kind": kind,
                    "required": "required" in attrs
                    or attrs.get("aria-required") == "true"
                    or "wpcf7-validates-as-required" in (attrs.get("class") or "").split(),
                    "checkbox_value": (attrs.get("value") or "on") if kind == "checkbox" else "",
                }
            )
        self.current["radios"] += kind == "radio"
        self.current["selects"] += kind == "select"
        self.current["checkboxes"] += kind == "checkbox"
        self.current["checked"] += kind == "checkbox" and "checked" in attrs
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
            "hidden",
            "submit",
            "button",
            "reset",
        }
        if len(self.current["names"]) > 100:
            raise ValueError("control limit")

    def handle_endtag(self, tag):
        if tag == "script" and self.script is not None:
            self.scripts.append(self.script)
            self.script = None
        if tag == "form":
            self.current = None

    def handle_data(self, data):
        if self.script is not None:
            self.script += data

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)


def contract_shape(form: dict | None) -> dict | None:
    if form is None or not form["marker"]:
        return None
    hidden = form["hidden"]
    form_id = hidden.get("_wpcf7", "")
    container = hidden.get("_wpcf7_container_post", "")
    id_valid = bool(re.fullmatch(r"[1-9][0-9]{0,9}", form_id)) and int(form_id) <= 2147483647
    container_valid = bool(re.fullmatch(r"0|[1-9][0-9]*", container))
    unit_prefix = "wpcf7-f" + form_id + ("-p" + container if container != "0" else "")
    hidden_complete = CONTRACT_MARKERS <= hidden.keys()
    hidden_valid = (
        hidden_complete
        and id_valid
        and container_valid
        and hidden.get("_wpcf7_version") in {"6.1.4", "6.2"}
        and bool(re.fullmatch(r"[a-z]{2,3}(?:_[A-Z]{2})?", hidden.get("_wpcf7_locale", "")))
        and bool(
            re.fullmatch(
                re.escape(unit_prefix) + r"-o[1-9][0-9]*", hidden.get("_wpcf7_unit_tag", "")
            )
        )
        and hidden.get("_wpcf7_posted_data_hash") == ""
    )
    names = form["visible_names"]
    return {
        "reviewed_lab_version": form["version"] == "6.1.4",
        "hidden_complete": hidden_complete,
        "hidden_shape_valid": hidden_valid and form["version"] == "6.1.4",
        "review_hidden_shape_valid": hidden_valid,
        "extra_hidden": len(hidden.keys() - CONTRACT_MARKERS),
        "invalid_names": sum(
            not bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,99}", name)) for name in names
        ),
        "repeated_names": len(names) - len(set(names)),
        "radio_controls": form["radios"],
        "select_controls": form["selects"],
        "checkbox_controls": form["checkboxes"],
        "checked_checkboxes": form["checked"],
        "disabled_controls": form["disabled"],
    }


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
        "contract_shape": contract_shape(form),
        "contract_evidence": contract_evidence(parser, form),
        "execution_allowed": False,
        "eligible_for_approval": False,
    }


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def contract_evidence(parser: Inspector, form: dict | None) -> dict | None:
    """Allowlist metadata only. Never execute JS or retain raw HTML/visible defaults."""
    shape = contract_shape(form)
    if not form or not shape or not shape["review_hidden_shape_valid"]:
        return None
    if (
        parser.base_override
        or parser.external_control
        or form["custom"]
        or not parser.rest_same_origin
        or not form["post"]
        or not form["enctype"]
        or any(
            shape[k]
            for k in (
                "extra_hidden",
                "invalid_names",
                "repeated_names",
                "radio_controls",
                "select_controls",
                "disabled_controls",
            )
        )
        or form["files"]
        or form["missing"]
        or form["unsupported"]
        or not 1 <= len(form["controls"]) <= 50
        or any(
            not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", c["checkbox_value"])
            for c in form["controls"]
            if c["kind"] == "checkbox"
        )
    ):
        return None
    configs = []
    try:
        decoder = json.JSONDecoder(object_pairs_hook=unique_object)
        for script in parser.scripts:
            for match in re.finditer(r"\bvar\s+wpcf7\s*=\s*", script):
                value, end = decoder.raw_decode(script[match.end() :])
                if not script[match.end() + end :].lstrip().startswith(";"):
                    return None
                configs.append(value)
        if len(configs) != 1 or set(configs[0]) != {"api"}:
            return None
        api = configs[0]["api"]
        if set(api) != {"root", "namespace"} or api["namespace"] != "contact-form-7/v1":
            return None
        source = urlsplit(parser.url)
        root = source.scheme + "://" + source.netloc + "/wp-json/"
        if source.scheme != "https" or api["root"] != root:
            return None
        return {
            "definition_version": "real-cf7-static-evidence-v1",
            "source_kind": "REAL_SITE_STATIC_HTML",
            "form_url": parser.url,
            "plugin_version": form["version"],
            "rest_root": root,
            "endpoint": root
            + "contact-form-7/v1/contact-forms/"
            + form["hidden"]["_wpcf7"]
            + "/feedback",
            "hidden": form["hidden"],
            "controls": form["controls"],
            "dom_order": form["order"],
            "execution_allowed": False,
            "eligible_for_approval": False,
        }
    except (ValueError, TypeError, KeyError):
        return None


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
