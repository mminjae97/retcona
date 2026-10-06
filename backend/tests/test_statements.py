from pipeline.statements import location_statement


def test_a_feature_that_is_a_noun_phrase_reads_as_what_the_place_is():
    assert location_statement("검은 숲", "안개 낀 숲") == "검은 숲은 안개 낀 숲이다."
    assert location_statement("검은 숲", "캐나다") == "검은 숲은 캐나다이다."


def test_a_feature_that_is_what_a_sentence_says_of_the_place_reads_as_that():
    assert location_statement("검은 숲", "한없이 넓다") == "검은 숲은 한없이 넓다."
    assert location_statement("검은 숲", "늘 안개로 덮여 있었다.") == "검은 숲은 늘 안개로 덮여 있었다."
    assert location_statement("검은 숲", "안개가 짙었고") == "검은 숲은 안개가 짙었고."
