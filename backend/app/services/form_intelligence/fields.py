"""Field-local evidence; never use unrelated fields to infer a destination."""

import re

from bs4 import BeautifulSoup
from bs4.element import Tag

from app.services.form_intelligence.rules import dom_mapping, normalize, rule_mapping


def _local_context(element: Tag, form: Tag) -> str:
    row = element.find_parent("tr")
    if row and row.find_parent("form") is form:
        heading = row.find(["th", "td"])
        if heading and not heading.select("input,textarea,select,button"):
            return heading.get_text(" ", strip=True)[:1000]
    cell = element.find_parent("dd")
    if cell:
        heading = cell.find_previous_sibling("dt")
        if heading:
            return heading.get_text(" ", strip=True)[:1000]
    for parent in element.parents:
        if parent is form:
            break
        if parent.name not in {"div", "p", "li", "td", "fieldset"}:
            continue
        controls = parent.select("input,textarea,select")
        keys = {(c.get("name") or id(c)) for c in controls if c.get("type") != "hidden"}
        if len(keys) != 1:
            continue
        # Remove control values/options and labels for individual radio choices.
        clone = BeautifulSoup(str(parent), "html.parser")
        for label in clone.select("label"):
            if label.select_one('input[type="radio"],input[type="checkbox"]'):
                label.decompose()
        for control in clone.select("input,textarea,select,button,script,style"):
            control.decompose()
        text = clone.get_text(" ", strip=True)[:1000]
        if text:
            return text
    return ""


def _field_label(element: Tag, form: Tag) -> str:
    element_id = str(element.get("id") or "")
    if element_id:
        label = form.find("label", attrs={"for": element_id})
        if label:
            return label.get_text(" ", strip=True)[:500]
    parent = element.find_parent("label")
    if parent:
        return parent.get_text(" ", strip=True)[:500]
    if element.get("aria-label"):
        return str(element["aria-label"])[:500]
    return (
        _local_context(element, form)
        or str(element.get("placeholder") or element.get("name") or "入力項目")
    )[:500]


def _required(element: Tag, form: Tag) -> bool:
    if element.has_attr("required") or str(element.get("aria-required", "")).lower() == "true":
        return True
    classes = set(element.get("class", []))
    if "wpcf7-validates-as-required" in classes:
        return True
    acceptance = element.find_parent(class_="wpcf7-acceptance")
    if acceptance and "optional" not in acceptance.get("class", []):
        return True
    text = normalize(_local_context(element, form) + " " + _field_label(element, form))
    return bool(re.search(r"必須|(?<![a-z])required(?![a-z])|[※＊*]\s*$", text))


def _selector(element: Tag, position: int) -> str:
    element_id = str(element.get("id") or "").replace('"', "")
    name = str(element.get("name") or "").replace('"', "")
    if element_id:
        return f'{element.name}[id="{element_id}"]'
    if name:
        return f'{element.name}[name="{name}"]'
    return f"{element.name}:nth-of-type({position + 1})"


def parse_form_fields(form: Tag) -> list[dict]:
    fields = []
    grouped = set()
    for element in form.select("input,textarea,select,button"):
        if element.has_attr("disabled"):
            continue
        field_type = (
            element.name if element.name != "input" else str(element.get("type") or "text").lower()
        )
        name = str(element.get("name") or "")[:500]
        group_key = (field_type, name)
        if field_type in {"radio", "checkbox"} and name:
            if group_key in grouped:
                continue
            grouped.add(group_key)
            group = [
                c
                for c in form.find_all("input", attrs={"type": field_type, "name": name})
                if not c.has_attr("disabled")
            ]
            options = [
                {"value": str(c.get("value") or "")[:500], "label": _field_label(c, form)}
                for c in group
            ]
            required = any(_required(c, form) for c in group)
        else:
            options = [
                {
                    "value": str(c.get("value") or c.get_text(" ", strip=True))[:500],
                    "label": c.get_text(" ", strip=True)[:500],
                }
                for c in element.select("option")
            ]
            required = _required(element, form)
        label = _field_label(element, form)
        surrounding = _local_context(element, form)
        mapped = dom_mapping(field_type, name)
        if field_type in {"hidden", "submit", "button", "reset", "image"}:
            mapped_key, confidence, source = "other", 1.0, "DOM"
        elif mapped:
            mapped_key, confidence, source = mapped[0], mapped[1], "DOM"
        else:
            # Choice labels such as 電話/メール are values, not field purposes.
            mapping_text = " ".join(
                filter(
                    None,
                    (
                        surrounding or label,
                        name,
                        str(element.get("id") or ""),
                        str(element.get("aria-label") or ""),
                    ),
                )
            )
            mapped_key, confidence = rule_mapping(mapping_text, field_type)
            source = "RULE"
        if mapped_key == "message" and field_type not in {"text", "textarea"}:
            mapped_key, confidence = "unknown", 0.0
        fields.append(
            {
                "position": len(fields),
                "selector": _selector(element, len(fields)),
                "element_id": str(element.get("id") or "")[:500],
                "label": label,
                "name": name,
                "field_type": field_type[:50],
                "required": required,
                "mapped_key": mapped_key,
                "confidence": confidence,
                "decision_source": source,
                "recommended_value": "",
                "options": options,
                "placeholder": str(element.get("placeholder") or "")[:500],
                "aria_label": str(element.get("aria-label") or "")[:500],
                "surrounding_text": surrounding,
            }
        )
    return fields


def mapping_review_reason(fields: list[dict]) -> str:
    relevant = [
        f for f in fields if f["field_type"] not in {"hidden", "submit", "button", "reset", "image"}
    ]
    message = [f for f in relevant if f["mapped_key"] == "message"]
    if not message:
        return "営業文面の本文を入力する項目が確認できません。"
    if len(message) != 1:
        return "本文の入力先が複数にマッピングされています。確認が必要です。"
    if message[0]["field_type"] not in {"text", "textarea"} or message[0]["confidence"] < 0.8:
        return "本文の入力先を確定できません。確認が必要です。"
    if any(
        f["required"] and (f["mapped_key"] == "unknown" or f["confidence"] < 0.8) for f in relevant
    ):
        return "必須項目の自動マッピングを確定できません。"
    return ""
