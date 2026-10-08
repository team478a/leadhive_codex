"""Deterministic cached recommendations. No score can promote a non-READY candidate."""

PURPOSE_PRIORITY = {"sales": 4, "partnership": 3, "business": 2, "general": 1}


def recommend(rows):
    eligible = [
        row
        for row in rows
        if row["status"] == "READY" and row["id"] and row["purpose"] in PURPOSE_PRIORITY
    ]
    if not eligible:
        return dict(
            recommended_destination=None,
            destination_selection_required=False,
            recommendation_reason="NO_READY_DESTINATION",
        )
    best = max(PURPOSE_PRIORITY[row["purpose"]] for row in eligible)
    winners = [row for row in eligible if PURPOSE_PRIORITY[row["purpose"]] == best]
    if len(winners) != 1:
        return dict(
            recommended_destination=None,
            destination_selection_required=True,
            recommendation_reason="EQUIVALENT_READY_DESTINATIONS",
        )
    row = winners[0]
    return dict(
        recommended_destination=dict(
            id=row["id"],
            type=row["type"],
            destination=row["destination"],
            purpose=row["purpose"],
            payload_hash=row["expected_hash"],
            execution_allowed=False,
        ),
        destination_selection_required=False,
        recommendation_reason="CURRENT_READY_PURPOSE_PRIORITY",
    )
