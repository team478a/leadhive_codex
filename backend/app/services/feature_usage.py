from app.models import FeatureUsageEvent


def add_feature_usage_event(db, event_type: str, outcome: str = "completed") -> None:
    db.add(FeatureUsageEvent(event_type=event_type, outcome=outcome))
