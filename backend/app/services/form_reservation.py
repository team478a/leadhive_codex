"""Conservative reservation-form detection shared by collection and analysis."""

import re
import unicodedata

from bs4 import BeautifulSoup
from bs4.element import Tag

from app.services.contact_discovery import is_contact_form

RESERVATION_SIGNAL_GROUPS = {
    "visit_date": ("来店日", "ご来店日", "来店希望日", "来店予定日"),
    "booking_date": ("予約日", "予約希望日", "予約日時"),
    "preferred_time": ("希望日時", "希望日", "希望時間", "希望時刻"),
    "party_size": ("人数", "名様"),
    "course": ("コース",),
}


def _normalized(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


def _form_identity_text(form: Tag) -> str:
    values = [form.get_text(" ", strip=True)]
    for field in form.select("input, select, textarea"):
        values.extend(
            str(field.get(key) or "")
            for key in ("name", "id", "placeholder", "aria-label", "title")
        )
        field_id = str(field.get("id") or "")
        if field_id:
            for label in form.select("label[for]"):
                if str(label.get("for") or "") == field_id:
                    values.append(label.get_text(" ", strip=True))
        parent_label = field.find_parent("label")
        if parent_label:
            values.append(parent_label.get_text(" ", strip=True))
    return _normalized(" ".join(values))


def is_reservation_form(
    form: Tag,
    *,
    page_title: str = "",
    contact_form_count: int = 1,
) -> bool:
    """Identify booking forms without treating a neighboring inquiry form as one."""
    if form.select_one("input[type='password'], input[type='search']"):
        return False
    heading = form.find_previous(re.compile(r"^h[1-6]$"))
    if heading and "予約" in _normalized(heading.get_text(" ", strip=True)):
        return True

    identity = _form_identity_text(form)
    matching_groups = sum(
        any(_normalized(term) in identity for term in terms)
        for terms in RESERVATION_SIGNAL_GROUPS.values()
    )
    if matching_groups >= 2:
        return True

    return contact_form_count == 1 and "予約" in _normalized(page_title)


def reservation_form_indices(html: str, *, contact_context: bool) -> set[int]:
    soup = BeautifulSoup(html, "html.parser")
    forms = list(soup.select("form"))
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    possible_forms = []
    for index, form in enumerate(forms):
        heading = form.find_previous(re.compile(r"^h[1-6]$"))
        has_reservation_context = bool(
            (heading and "予約" in _normalized(heading.get_text(" ", strip=True)))
            or (len(forms) == 1 and "予約" in _normalized(page_title))
        )
        has_multiple_reservation_signals = (
            sum(
                any(_normalized(term) in _form_identity_text(form) for term in terms)
                for terms in RESERVATION_SIGNAL_GROUPS.values()
            )
            >= 2
        )
        if (
            is_contact_form(form, contact_context=contact_context)
            or has_reservation_context
            or has_multiple_reservation_signals
        ):
            possible_forms.append((index, form))
    return {
        index
        for index, form in possible_forms
        if is_reservation_form(
            form,
            page_title=page_title,
            contact_form_count=len(possible_forms),
        )
    }


def reservation_js_container(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    containers = soup.select("div, section, fieldset, [role='form']")
    candidates = []
    for container in containers:
        identity = " ".join(
            str(container.get(key) or "") for key in ("id", "aria-label", "role")
        ).lower()
        if (
            "contact" not in identity
            and "inquiry" not in identity
            and "お問い合わせ" not in identity
        ):
            continue
        if container.find_parent("form") or container.select_one("form"):
            continue
        candidates.append(container)
    if len(candidates) != 1:
        return False
    candidate = candidates[0]
    heading = candidate.find_previous(re.compile(r"^h[1-6]$"))
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    return bool(
        (heading and "予約" in _normalized(heading.get_text(" ", strip=True)))
        or "予約" in _normalized(title)
        or sum(
            any(_normalized(term) in _form_identity_text(candidate) for term in terms)
            for terms in RESERVATION_SIGNAL_GROUPS.values()
        )
        >= 2
    )
