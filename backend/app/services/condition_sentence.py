"""Small Japanese sentence forms; no inference, network, or query expansion."""

import re


def prepare(clauses: list[str], media: dict[str, str]) -> tuple[list[str], int | None]:
    expanded: list[str] = []
    counts: list[int] = []
    for clause in clauses:
        count = re.search(
            r"(?:を)?([0-9]+)件(?:程度)?(?:探す|探して|集める|集めて|収集する)?$", clause
        )
        if count and (
            not 1 <= int(count[1]) <= 1000 or re.search(r"[0-9.+\-]$", clause[: count.start()])
        ):
            expanded.append("未対応の件数指定:" + clause)
            continue
        if count and not re.search(r"[0-9.+\-]$", clause[: count.start()]):
            number = int(count[1])
            if 1 <= number <= 1000:
                counts.append(number)
                remaining = clause[: count.start()].removesuffix("の店舗").strip()
                clause = remaining or clause
        region = re.fullmatch(r"([^:]+?(?:市|区|町|村))の([^で:]+?)(?:で(.*))?", clause)
        if region and not clause.startswith(("希望", "除外", "できれば")):
            expanded.extend([f"地域:{region[1]}", f"業種:{region[2]}"])
            if region[3]:
                expanded.append(region[3])
        else:
            expanded.append(clause)
    rows: list[str] = []
    for clause in expanded:
        if clause.startswith("できれば"):
            clause = "希望:" + clause.removeprefix("できれば")
        prefix = re.match(r"^(必須|希望|除外|MUST|WANT|EXCLUDE)\s*:\s*(.+)$", clause, re.I)
        priority, content = (prefix[1] + ":", prefix[2]) if prefix else ("", clause)
        common = re.fullmatch(r"(.+?)(?:が)?(?:ある|あり)(?:店舗|ところ)?", content)
        labels = common[1].split("と") if common else []
        if len(labels) > 1 and all(
            label.casefold().strip() in media or label.strip() == "公式サイト" for label in labels
        ):
            rows.extend(priority + label.strip() + "あり" for label in labels)
            continue
        listed = re.fullmatch(
            r"(.+?)に掲載(?:している|していて|されている|されていて)(?:店舗)?", content
        )
        if listed and listed[1].casefold().strip() in media:
            content = listed[1].strip() + "掲載あり"
        rows.append(priority + content)
    # Ambiguous targets remain explicitly unresolved instead of last-value-wins.
    if len(counts) > 1:
        rows.append("件数が複数指定されています。目標件数を確認してください")
    return rows, counts[0] if len(counts) == 1 else None
