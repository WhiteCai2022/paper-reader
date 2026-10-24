import pytest

from backend.quote_matching import quote_matches


@pytest.mark.parametrize("quote,source", [
    ("improves learning efficiency", "We find it improves learning efﬁciency in trials."),
    ("stability constraints and decisions", "We enforce stability con-\nstraints and de-\ncisions over time."),
    ("DNN-based tasks under constraints", "These DNN-\nbased tasks under con-\nstraints are evaluated."),
    ("DNN-\nbased tasks under con-\nstraints", "These DNN-based tasks under constraints are evaluated."),
    ("efficient inference models", "We study ef\u00adficient infer\u00ad\nence models in detail."),
    ("the source\n\t contains whitespace", "Here the source contains   whitespace at page end."),
    ("In this paper, the queues are stable.", "1In this paper, the queues are stable. A PDF footnote follows."),
    ("任务需要满足时延约束， 并保证队列稳定。", "任务需要满足时延约\n束，\n并保证队列稳定。"),
    ("动态分配计算资源", "本文研究动态分配\n计算资源的机制与条件。"),
    ("通过调整分区位置降低系统开销。", "通过调 整分区位置降低系统开销。"),
])
def test_layout_equivalent_quotes_return_actual_source_slices(quote, source):
    matches = quote_matches(quote, source)
    assert len(matches) == 1 and matches[0] in source


@pytest.mark.parametrize("quote,source", [
    ("latency is 10 ms", "The latency is 100 ms in this setup."),
    ("latency is 100 ms", "The latency is 10 0 ms in this setup."),
    ("a rate of 0.5 Hz", "We use a rate of 0.6 Hz here."),
    ("budget x >= 1", "The budget x ≤ 1 is required."),
    ("reliable DNNbased tasks", "We run reliable DNN-based tasks on devices."),
    ("We study efficient inference", "WE STUDY EFFICIENT INFERENCE."),
    ("choose the larger value", "We choose the smaller value in tests."),
    ("the value is 12", "Here the value is 1-\n2 exactly."),
    ("inference efficiency", "We study inXference efficiency instead."),
    ("quote with\x00marker", "A quote with marker exists."),
    ("the square x2 is bounded", "Here the square x² is bounded."),
    ("the state x1 is tracked", "Here the state x₁ is tracked."),
    ("the weight x is positive", "Here the weight 𝑥 is positive."),
    ("时延上限为10毫秒", "时延上限为1 0毫秒"),
    ("模型条件x ≥ 1", "模型条件x ≤ 1"),
    ("任务的到达率为0.5", "任务的到达率为0.6"),
    ("通过减少计算资源降低开销", "通过增加计算资源降低开销"),
    ("机制作用系统结果", "机制作用-\n系统结果"),
])
def test_changed_values_signs_case_words_and_real_hyphens_never_match(quote, source):
    assert quote_matches(quote, source) == []


def test_repeated_quotes_and_overlapping_occurrences_are_ambiguous():
    assert len(quote_matches("Repeated original sentence.", "Repeated original sentence. Repeated original sentence.")) == 2
    assert quote_matches("", "text") == []
