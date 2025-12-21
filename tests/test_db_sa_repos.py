from api.db_sa import BlacklistRepo, SettingsRepo, SpotifyTracksRepo, UserRepo


def test_user_repo_upsert_and_exists(db):
    users = UserRepo(db)

    assert users.exists(1) is False
    users.upsert_user(1, "alice", "Alice", None, is_admin=False)
    assert users.exists(1) is True
    assert users.count() == 1


def test_blacklist_repo_matches(db):
    blacklist = BlacklistRepo(db)

    assert blacklist.matches("alice") is False
    blacklist.add("@alice", note="bad")
    assert blacklist.matches("@alice") is True
    assert blacklist.matches("alice") is True


def test_settings_repo_get_set(db):
    settings = SettingsRepo(db)

    assert settings.get("allow_new_users", "1") == "1"
    settings.set("allow_new_users", "0")
    assert settings.get("allow_new_users", "1") == "0"


def test_spotify_tracks_repo_add_list_delete(db):
    tracks = SpotifyTracksRepo(db)

    assert tracks.count_by_user(10) == 0
    ok = tracks.add_track(
        spotify_id="sp1",
        name="Song",
        artist="Artist",
        url="https://example.com",
        added_by=10,
    )
    assert ok is True
    assert tracks.exists_spotify_id("sp1") is True
    assert tracks.count_by_user(10) == 1

    items = tracks.list_by_user(10)
    assert len(items) == 1
    assert items[0][0] == "sp1"

    deleted = tracks.delete_by_user(10, "sp1")
    assert deleted == 1
    assert tracks.count_by_user(10) == 0
