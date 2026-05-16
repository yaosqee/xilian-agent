"""MarkerParser 单元测试 — 阶段 7c"""
import pytest
from packages.shared.marker_parser import MarkerParser, ParsedToken


class TestMarkerTypes:
    """5 种标记类型正确解析"""

    def test_emotion_marker(self):
        parser = MarkerParser()
        tokens = parser.feed('[emotion:joy:0.8]') + parser.flush()
        assert len(tokens) == 1
        assert tokens[0].kind == 'special'
        assert tokens[0].marker_type == 'emotion'
        assert tokens[0].payload == {'emotion': 'joy', 'intensity': 0.8}

    def test_action_marker(self):
        parser = MarkerParser()
        tokens = parser.feed('[action:thinking]') + parser.flush()
        assert tokens[0].marker_type == 'action'
        assert tokens[0].payload == {'action': 'thinking'}

    def test_pause_marker(self):
        parser = MarkerParser()
        tokens = parser.feed('[pause:1.5]') + parser.flush()
        assert tokens[0].marker_type == 'pause'
        assert tokens[0].payload == {'seconds': 1.5}

    def test_emph_marker(self):
        parser = MarkerParser()
        tokens = parser.feed('[emph:重要]') + parser.flush()
        assert tokens[0].marker_type == 'emph'
        assert tokens[0].payload == {'text': '重要'}

    def test_whisper_marker(self):
        parser = MarkerParser()
        tokens = parser.feed('[whisper:悄悄话]') + parser.flush()
        assert tokens[0].marker_type == 'whisper'
        assert tokens[0].payload == {'text': '悄悄话'}

    def test_unknown_bracket_is_literal(self):
        """无法识别的 [xxx] 当作 literal"""
        parser = MarkerParser()
        tokens = parser.feed('[unknown:thing]') + parser.flush()
        assert tokens[0].kind == 'literal'


class TestStreaming:
    """跨 chunk 边界解析"""

    def test_cross_chunk_emotion(self):
        parser = MarkerParser()
        t1 = parser.feed('[emo')
        assert len(t1) == 0  # 未闭合，无输出
        t2 = parser.feed('tion:joy:0.8] 开心~')
        tokens = t1 + t2 + parser.flush()
        specials = [t for t in tokens if t.kind == 'special']
        assert len(specials) == 1
        assert specials[0].marker_type == 'emotion'

    def test_cross_chunk_action(self):
        parser = MarkerParser()
        parser.feed('[acti')
        tokens = parser.feed('on:nod] hi') + parser.flush()
        assert any(t.marker_type == 'action' for t in tokens)

    def test_multiple_chunks(self):
        parser = MarkerParser()
        all_tokens = []
        all_tokens += parser.feed('文字1 [emotion:calm:')
        all_tokens += parser.feed('0.5] 文字2 [action:')
        all_tokens += parser.feed('smile] 文字3')
        all_tokens += parser.flush()
        specials = [t for t in all_tokens if t.kind == 'special']
        literals = [t for t in all_tokens if t.kind == 'literal']
        assert len(specials) == 2
        assert '文字1' in ''.join(t.text for t in literals)
        assert '文字2' in ''.join(t.text for t in literals)
        assert '文字3' in ''.join(t.text for t in literals)


class TestEdgeCases:
    """边界情况"""

    def test_pure_literal(self):
        parser = MarkerParser()
        tokens = parser.feed('纯文本无标记') + parser.flush()
        assert len(tokens) == 1
        assert tokens[0].kind == 'literal'
        assert tokens[0].text == '纯文本无标记'

    def test_pure_markers(self):
        parser = MarkerParser()
        tokens = parser.feed('[action:thinking][emotion:calm:0.5]') + parser.flush()
        assert all(t.kind == 'special' for t in tokens)
        assert len(tokens) == 2

    def test_empty_input(self):
        parser = MarkerParser()
        assert parser.feed('') == []
        assert parser.flush() == []

    def test_mixed_text_and_markers(self):
        parser = MarkerParser()
        tokens = parser.feed('今天[emotion:joy:0.9]真开心[action:smile]呢~') + parser.flush()
        literal_text = ''.join(t.text for t in tokens if t.kind == 'literal')
        assert '今天' in literal_text
        assert '真开心' in literal_text
        assert '呢~' in literal_text
        assert '[emotion' not in literal_text

    def test_flush_returns_remaining(self):
        parser = MarkerParser()
        parser.feed('说了半句 ')
        parser.feed('[unclosed')
        tokens = parser.flush()
        assert len(tokens) == 1
        assert tokens[0].kind == 'literal'
        assert '[unclosed' in tokens[0].text
