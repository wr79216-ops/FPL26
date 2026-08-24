from src.utils.text import normalize_display_name


def test_display_names_are_easy_to_type_without_changing_normal_names() -> None:
    assert normalize_display_name("Ødegaard") == "Odegaard"
    assert normalize_display_name("Højlund") == "Hojlund"
    assert normalize_display_name("João Félix") == "Joao Felix"
    assert normalize_display_name("Bukayo Saka") == "Bukayo Saka"
