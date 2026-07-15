"""Tests for the core input data models."""

from app.models import Category, LeaderboardRow, Participant


def test_leaderboard_row_from_scrape_parses_result_and_strips() -> None:
    row = LeaderboardRow.from_scrape(
        athlete_name="  Ivan Petrov ",
        athlete_id=" 12345 ",
        raw_result=" 5:23 ",
        rank=1,
        date="Aug 5, 2025",
    )
    assert row.athlete_name == "Ivan Petrov"
    assert row.athlete_id == "12345"
    assert row.raw_result == "5:23"
    assert row.result_seconds == 323.0
    assert row.rank == 1


def test_leaderboard_row_from_scrape_keeps_none_for_unparsable_result() -> None:
    row = LeaderboardRow.from_scrape(athlete_name="A", athlete_id="1", raw_result="-")
    assert row.result_seconds is None


def test_leaderboard_row_dict_roundtrip() -> None:
    row = LeaderboardRow.from_scrape(
        athlete_name="A", athlete_id="1", raw_result="1:00", rank=2, date="d"
    )
    assert LeaderboardRow.from_dict(row.to_dict()) == row


def test_category_from_api_defaults() -> None:
    cat = Category.from_api({"id": 7, "name": "3.5+", "male": True, "female": False})
    assert cat.id == 7
    assert cat.name == "3.5+"
    assert cat.bib_from == 1
    assert cat.bib_to == 20000


def test_participant_from_api_and_display_name() -> None:
    p = Participant.from_api(
        {
            "id": 3,
            "first_name": "Ivan",
            "last_name": "Petrov",
            "participant_names": "Petrov Ivan",
            "category_id": 7,
            "category_name": "3.5+",
            "additional_info": "https://strava.com/athletes/999",
            "birth_year": 1990,
        }
    )
    assert p.display_name == "Petrov Ivan"
    assert p.category_id == 7
    assert p.additional_info.endswith("999")


def test_participant_display_name_falls_back_to_last_first() -> None:
    p = Participant.from_api(
        {
            "id": 3,
            "first_name": "Ivan",
            "last_name": "Petrov",
            "participant_names": "",
            "category_id": None,
            "category_name": "",
            "additional_info": "",
        }
    )
    assert p.display_name == "Petrov Ivan"
