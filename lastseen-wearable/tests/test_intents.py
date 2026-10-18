import pytest

from lastseen.brain.intents import Intent, parse_question
from lastseen.config import load_config

ITEMS = load_config("config.yaml").items


@pytest.mark.parametrize(
    "text",
    [
        "where are my airpods",
        "I can't find my earbuds",
        "have you seen my AirPods case",
        "where did I put my headphones",
        "airpods?",
        "Where’s my AirPods, please?",
        "  WHERE ARE MY AIRPODS right now?! ",
    ],
)
def test_airpods_phrasings(text):
    i = parse_question(text, ITEMS)
    assert i.kind == "find" and i.item_id == "airpods"


@pytest.mark.parametrize(
    "text,item",
    [
        ("Where's my water bottle?", "water_bottle"),
        ("where are my keys", "keys"),
        ("where are my glasses", "glasses"),
    ],
)
def test_other_items(text, item):
    i = parse_question(text, ITEMS)
    assert i.kind == "find" and i.item_id == item


def test_held_time():
    i = parse_question("when did I last have my glasses", ITEMS)
    assert (i.kind, i.item_id) == ("held_time", "glasses")


def test_enroll():
    i = parse_question("enroll my water bottle", ITEMS)
    assert (i.kind, i.item_id) == ("enroll", "water_bottle")


def test_unknown_item():
    i = parse_question("where's my passport", ITEMS)
    assert i.kind == "find" and i.item_id is None and i.raw_item == "passport"


def test_chatter_ignored():
    assert parse_question("what a nice day", ITEMS).kind == "none"
    assert parse_question("I love my airpods", ITEMS).kind == "none"
    assert parse_question("airpods", ITEMS).kind == "none"
    assert parse_question("", ITEMS).kind == "none"


def test_fuzzy():
    assert parse_question("where are my air pod", ITEMS).item_id == "airpods"
    assert parse_question("air pod?", ITEMS).kind == "find"


@pytest.mark.parametrize(
    "text",
    [
        "where's my phone?",
        "where is my car",
        "where is my case",
        "where is my passport",
        "where is my head",
        "where is the water heater",
        "where's the deck chair",
        "where are my credit cards",
    ],
)
def test_no_guessing_unknown_items(text):
    i = parse_question(text, ITEMS)
    assert i.kind == "find" and i.item_id is None


@pytest.mark.parametrize(
    "text",
    [
        "is the water running?",
        "what do I do with my glasses?",
        "where is",
        "where are my",
        "where are you going",
        "air?",
        "head?",
    ],
)
def test_no_guessing_none(text):
    assert parse_question(text, ITEMS).kind == "none"


def test_typos_still_resolve():
    assert parse_question("where are my airpod", ITEMS).item_id == "airpods"
    assert parse_question("where are my glases", ITEMS).item_id == "glasses"
