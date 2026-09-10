CLIENT_IDS = (1, 2, 3)
FULL_SCREEN_WINDOWS = {"Tum Ekran", "Tüm Ekran"}


def shared_rumeli2_calibration_updates(question_region, option_regions, calibration_size):
    """Build independent copies of one normalized calibration for every client."""
    return {
        client_id: {
            "rumeli2_question_region": list(question_region),
            "rumeli2_option_regions": [list(region) for region in option_regions],
            "rumeli2_calibration_size": list(calibration_size),
        }
        for client_id in CLIENT_IDS
    }


def validate_client_assignment(client_id, proposed, client_configs):
    """Return a user-facing error when an input target is ambiguous."""
    if client_id not in CLIENT_IDS:
        return "Gecersiz istemci"

    selected_active = bool(proposed.get("aktif", True))
    selected_window = proposed.get("pencere", "Yok")
    if not selected_active or selected_window == "Yok":
        return None

    for other_id in CLIENT_IDS:
        if other_id == client_id:
            continue
        other = client_configs.get(other_id, {})
        if not other.get("aktif", True):
            continue
        other_window = other.get("pencere", "Yok")
        if other_window == "Yok":
            continue
        if selected_window in FULL_SCREEN_WINDOWS or other_window in FULL_SCREEN_WINDOWS:
            return "Coklu istemcide Tum Ekran yerine oyun penceresini secin"
        if selected_window == other_window:
            return f"Bu pencere Client {other_id} tarafindan kullaniliyor"
    return None


def duplicate_client_ids(client_configs):
    """Find active clients that point to the same physical window."""
    owners = {}
    duplicates = set()
    active = []
    for client_id in CLIENT_IDS:
        cfg = client_configs.get(client_id, {})
        selected_window = cfg.get("pencere", "Yok")
        if not cfg.get("aktif", True) or selected_window == "Yok":
            continue
        active.append((client_id, selected_window))
        if selected_window in owners:
            duplicates.add(owners[selected_window])
            duplicates.add(client_id)
        else:
            owners[selected_window] = client_id
    if len(active) > 1 and any(window in FULL_SCREEN_WINDOWS for _client_id, window in active):
        duplicates.update(client_id for client_id, _window in active)
    return duplicates
