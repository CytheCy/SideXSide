"""Two-pass, Markdown-aware prose comparison with source character offsets."""

from __future__ import annotations

from dataclasses import dataclass, replace
from difflib import SequenceMatcher
import re


TOKEN_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*|_+|--|[^\w\s]|\s+", re.UNICODE)
WORD_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)
STRUCTURAL_RE = re.compile(r"^\s*(?:#{1,6}\s|>\s?|[-*+]\s|\d+[.)]\s)")
SENTENCE_END_RE = re.compile(r"[.!?]+[\"”’']*(?=\s|$)")


@dataclass(frozen=True)
class Block:
    text: str
    start: int
    end: int
    line: int
    kind: str


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    kind: str  # insert, delete, replace


@dataclass(frozen=True)
class Change:
    kind: str
    left: int | None
    right: int | None
    left_offset: int | None = None
    right_offset: int | None = None
    left_end: int | None = None
    right_end: int | None = None


@dataclass(frozen=True)
class DiffResult:
    left_blocks: tuple[Block, ...]
    right_blocks: tuple[Block, ...]
    left_spans: tuple[Span, ...]
    right_spans: tuple[Span, ...]
    changes: tuple[Change, ...]
    alignments: tuple[tuple[int, int], ...]
    rows: tuple[tuple[int | None, int | None], ...]
    left_words: int
    right_words: int

    @property
    def edit_count(self) -> int:
        return len(self.changes)


def segment_blocks(text: str, ignore_paragraph_spacing: bool = False) -> tuple[Block, ...]:
    """Group prose lines; keep headings, quotes, list items and blank runs distinct."""
    blocks: list[Block] = []
    offset = 0
    line_number = 1
    for line in text.splitlines(keepends=True):
        kind = "blank" if not line.strip() else "structural" if STRUCTURAL_RE.match(line) else "prose"
        if ignore_paragraph_spacing and kind == "blank":
            if blocks and blocks[-1].kind == "prose":
                old = blocks[-1]
                blocks[-1] = Block(old.text + line, old.start, offset + len(line), old.line, old.kind)
            offset += len(line)
            line_number += 1
            continue
        if blocks and kind in ("prose", "blank") and blocks[-1].kind == kind:
            old = blocks[-1]
            blocks[-1] = Block(old.text + line, old.start, offset + len(line), old.line, kind)
        else:
            blocks.append(Block(line, offset, offset + len(line), line_number, kind))
        offset += len(line)
        line_number += 1
    return tuple(blocks)


def segment_sentences(block: Block) -> tuple[Block, ...]:
    """Keep source offsets while dividing a paragraph at prose sentence endings."""
    segments: list[Block] = []
    start = 0
    for match in SENTENCE_END_RE.finditer(block.text):
        end = match.end()
        while end < len(block.text) and block.text[end].isspace():
            end += 1
        if end <= start:
            continue
        segments.append(Block(block.text[start:end], block.start + start, block.start + end,
                              block.line + block.text[:start].count("\n"), "sentence"))
        start = end
    if start < len(block.text):
        segments.append(Block(block.text[start:], block.start + start, block.end,
                              block.line + block.text[:start].count("\n"), "sentence"))
    return tuple(segments)


def _tokens(block: Block, ignore_whitespace: bool, strict_markdown: bool) -> list[tuple[str, int, int]]:
    result = []
    for match in TOKEN_RE.finditer(block.text):
        value = match.group()
        if ignore_whitespace and value.isspace():
            continue
        if not strict_markdown and value in ("*", "_", "__", "***"):
            continue
        result.append((value, block.start + match.start(), block.start + match.end()))
    return result


def _key(block: Block, ignore_whitespace: bool, strict_markdown: bool) -> tuple[str, ...]:
    return tuple(token for token, _, _ in _tokens(block, ignore_whitespace, strict_markdown))


def _pair_replacement(
    left: tuple[Block, ...], right: tuple[Block, ...],
    li: list[int], ri: list[int], ignore_whitespace: bool, strict_markdown: bool,
) -> list[tuple[int | None, int | None]]:
    """Align changed runs by token similarity while retaining paragraph order."""
    n, m = len(li), len(ri)
    if not n:
        return [(None, j) for j in ri]
    if not m:
        return [(i, None) for i in li]
    left_keys = [_key(left[index], ignore_whitespace, strict_markdown) for index in li]
    right_keys = [_key(right[index], ignore_whitespace, strict_markdown) for index in ri]

    if n * m > 4096:
        # A fully reworked chapter can have hundreds of changed paragraphs.
        # Keep alignment linear in that case, with a short insertion lookahead.
        pairs: list[tuple[int | None, int | None]] = []
        i = j = 0
        while i < n and j < m:
            current = SequenceMatcher(None, left_keys[i], right_keys[j], autojunk=False).ratio()
            if i + 1 < n and n - i > m - j:
                following = SequenceMatcher(None, left_keys[i + 1], right_keys[j], autojunk=False).ratio()
                if following > current + .18:
                    pairs.append((li[i], None))
                    i += 1
                    continue
            if j + 1 < m and m - j > n - i:
                following = SequenceMatcher(None, left_keys[i], right_keys[j + 1], autojunk=False).ratio()
                if following > current + .18:
                    pairs.append((None, ri[j]))
                    j += 1
                    continue
            pairs.append((li[i], ri[j]))
            i += 1
            j += 1
        pairs.extend((li[index], None) for index in range(i, n))
        pairs.extend((None, ri[index]) for index in range(j, m))
        return pairs
    scores = [[0.0] * (m + 1) for _ in range(n + 1)]
    steps = [[""] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        scores[i][0], steps[i][0] = scores[i - 1][0] - .35, "left"
    for j in range(1, m + 1):
        scores[0][j], steps[0][j] = scores[0][j - 1] - .35, "right"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            ratio = SequenceMatcher(None, left_keys[i - 1], right_keys[j - 1], autojunk=False).ratio()
            candidates = (
                (scores[i - 1][j - 1] + ratio - .15, "pair"),
                (scores[i - 1][j] - .35, "left"),
                (scores[i][j - 1] - .35, "right"),
            )
            scores[i][j], steps[i][j] = max(candidates, key=lambda item: item[0])
    pairs: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i or j:
        step = steps[i][j]
        if step == "pair":
            i -= 1
            j -= 1
            pairs.append((li[i], ri[j]))
        elif step == "left":
            i -= 1
            pairs.append((li[i], None))
        else:
            j -= 1
            pairs.append((None, ri[j]))
    pairs.reverse()
    return pairs


def _compare_tokens(
    left: Block, right: Block, left_index: int, right_index: int,
    ignore_whitespace: bool, strict_markdown: bool,
    left_spans: list[Span], right_spans: list[Span], changes: list[Change],
) -> None:
    """Record the smallest changed token runs inside two pieces of prose."""
    a = _tokens(left, ignore_whitespace, strict_markdown)
    b = _tokens(right, ignore_whitespace, strict_markdown)
    # Match words and punctuation first. Spaces occur too often to serve as
    # useful anchors, especially when paragraphs have been reflowed.
    a_content = [(token[0], index) for index, token in enumerate(a) if not token[0].isspace()]
    b_content = [(token[0], index) for index, token in enumerate(b) if not token[0].isspace()]
    a_values = [value for value, _ in a_content]
    b_values = [value for value, _ in b_content]
    start = 0
    while start < min(len(a_values), len(b_values)) and a_values[start] == b_values[start]:
        start += 1
    a_end, b_end = len(a_values), len(b_values)
    while a_end > start and b_end > start and a_values[a_end - 1] == b_values[b_end - 1]:
        a_end -= 1
        b_end -= 1
    matcher = SequenceMatcher(None, a_values[start:a_end], b_values[start:b_end],
                              autojunk=max(a_end - start, b_end - start) >= 2000)
    matches = [(index, index) for index in range(start)]
    for i, j, size in matcher.get_matching_blocks():
        matches.extend((start + i + k, start + j + k) for k in range(size))
    matches.extend((a_end + k, b_end + k) for k in range(len(a_values) - a_end))

    previous_a = previous_b = -1
    for current_a, current_b in (*matches, (len(a_content), len(b_content))):
        a1 = a_content[previous_a][1] + 1 if previous_a >= 0 else 0
        b1 = b_content[previous_b][1] + 1 if previous_b >= 0 else 0
        a2 = a_content[current_a][1] if current_a < len(a_content) else len(a)
        b2 = b_content[current_b][1] if current_b < len(b_content) else len(b)
        a_region = [token[0] for token in a[a1:a2]]
        b_region = [token[0] for token in b[b1:b2]]
        if a_region != b_region:
            region_matcher = SequenceMatcher(None, a_region, b_region,
                                             autojunk=max(len(a_region), len(b_region)) >= 200)
            for tag, i1, i2, j1, j2 in region_matcher.get_opcodes():
                if tag == "equal":
                    continue
                i1 += a1
                i2 += a1
                j1 += b1
                j2 += b1
                if i1 < i2:
                    left_spans.append(Span(a[i1][1], a[i2 - 1][2], tag))
                if j1 < j2:
                    right_spans.append(Span(b[j1][1], b[j2 - 1][2], tag))
                left_start = a[i1][1] if i1 < len(a) else left.end
                right_start = b[j1][1] if j1 < len(b) else right.end
                changes.append(Change(tag, left_index, right_index,
                                      left_start, right_start,
                                      a[i2 - 1][2] if i1 < i2 else left_start,
                                      b[j2 - 1][2] if j1 < j2 else right_start))
        previous_a, previous_b = current_a, current_b


def _compare_sentences(
    left: Block, right: Block, left_index: int, right_index: int,
    ignore_whitespace: bool, strict_markdown: bool,
    left_spans: list[Span], right_spans: list[Span], changes: list[Change],
) -> None:
    left_sentences = segment_sentences(left)
    right_sentences = segment_sentences(right)
    matcher = SequenceMatcher(
        None,
        [_key(sentence, ignore_whitespace, strict_markdown) for sentence in left_sentences],
        [_key(sentence, ignore_whitespace, strict_markdown) for sentence in right_sentences],
        autojunk=False,
    )
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "insert":
            anchor = left_sentences[i1].start if i1 < len(left_sentences) else left.end
            for sentence in right_sentences[j1:j2]:
                right_spans.append(Span(sentence.start, sentence.end, "insert"))
                changes.append(Change("insert", left_index, right_index,
                                      anchor, sentence.start, anchor, sentence.end))
            continue
        if tag == "delete":
            anchor = right_sentences[j1].start if j1 < len(right_sentences) else right.end
            for sentence in left_sentences[i1:i2]:
                left_spans.append(Span(sentence.start, sentence.end, "delete"))
                changes.append(Change("delete", left_index, right_index,
                                      sentence.start, anchor, sentence.end, anchor))
            continue
        # A punctuation edit can join or split sentences. Compare the whole
        # changed run so words on either side can still match.
        left_run = Block("".join(s.text for s in left_sentences[i1:i2]),
                         left_sentences[i1].start, left_sentences[i2 - 1].end,
                         left_sentences[i1].line, "sentence")
        right_run = Block("".join(s.text for s in right_sentences[j1:j2]),
                          right_sentences[j1].start, right_sentences[j2 - 1].end,
                          right_sentences[j1].line, "sentence")
        _compare_tokens(left_run, right_run, left_index, right_index,
                        ignore_whitespace, strict_markdown,
                        left_spans, right_spans, changes)


def compare(
    left_text: str, right_text: str, *, ignore_whitespace: bool = False,
    strict_markdown: bool = False,
) -> DiffResult:
    left = segment_blocks(left_text, ignore_whitespace)
    right = segment_blocks(right_text, ignore_whitespace)
    left_ids = [i for i, block in enumerate(left) if not (ignore_whitespace and block.kind == "blank")]
    right_ids = [i for i, block in enumerate(right) if not (ignore_whitespace and block.kind == "blank")]
    matcher = SequenceMatcher(
        None,
        [_key(left[i], ignore_whitespace, strict_markdown) for i in left_ids],
        [_key(right[i], ignore_whitespace, strict_markdown) for i in right_ids],
        autojunk=True,
    )
    pairs: list[tuple[int | None, int | None]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        li, ri = left_ids[i1:i2], right_ids[j1:j2]
        if tag == "equal":
            pairs.extend(zip(li, ri))
        else:
            pairs.extend(_pair_replacement(left, right, li, ri, ignore_whitespace, strict_markdown))

    left_spans: list[Span] = []
    right_spans: list[Span] = []
    changes: list[Change] = []
    alignments: list[tuple[int, int]] = []
    index = 0
    while index < len(pairs):
        l_index, r_index = pairs[index]
        if l_index is not None and r_index is not None and (
            _key(left[l_index], ignore_whitespace, strict_markdown)
            == _key(right[r_index], ignore_whitespace, strict_markdown)
        ):
            alignments.append((l_index, r_index))
            index += 1
            continue

        # Keep exact block matches as anchors. If a changed run also contains
        # an unmatched block, compare all its text together: a moved paragraph
        # break should not turn the surrounding words into deletions/additions.
        run = []
        while index < len(pairs):
            li, ri = pairs[index]
            if li is not None and ri is not None and (
                _key(left[li], ignore_whitespace, strict_markdown)
                == _key(right[ri], ignore_whitespace, strict_markdown)
            ):
                break
            run.append((li, ri))
            index += 1
        for li, ri in run:
            if li is not None and ri is not None:
                alignments.append((li, ri))
        left_run_ids = [li for li, _ in run if li is not None]
        right_run_ids = [ri for _, ri in run if ri is not None]
        if left_run_ids and right_run_ids and any(li is None or ri is None for li, ri in run):
            left_run = Block("".join(left[li].text for li in left_run_ids),
                             left[left_run_ids[0]].start, left[left_run_ids[-1]].end,
                             left[left_run_ids[0]].line, "prose")
            right_run = Block("".join(right[ri].text for ri in right_run_ids),
                              right[right_run_ids[0]].start, right[right_run_ids[-1]].end,
                              right[right_run_ids[0]].line, "prose")
            _compare_tokens(left_run, right_run, left_run_ids[0], right_run_ids[0],
                            ignore_whitespace, strict_markdown,
                            left_spans, right_spans, changes)
        else:
            for li, ri in run:
                if li is None:
                    block = right[ri]
                    right_spans.append(Span(block.start, block.end, "insert"))
                    changes.append(Change("insert", None, ri, None, block.start, None, block.end))
                elif ri is None:
                    block = left[li]
                    left_spans.append(Span(block.start, block.end, "delete"))
                    changes.append(Change("delete", li, None, block.start, None, block.end, None))
                else:
                    _compare_sentences(left[li], right[ri], li, ri,
                                       ignore_whitespace, strict_markdown,
                                       left_spans, right_spans, changes)
    # A whole-block insertion or deletion still needs a position on the empty
    # side, so accepting either direction has an exact insertion point.
    pair_positions = {pair: position for position, pair in enumerate(pairs)}
    for change_index, change in enumerate(changes):
        if change.left_offset is not None and change.right_offset is not None:
            continue
        row_index = pair_positions[(change.left, change.right)]
        if change.left_offset is None:
            previous = next((left[li].end for li, _ in reversed(pairs[:row_index]) if li is not None), None)
            following = next((left[li].start for li, _ in pairs[row_index + 1:] if li is not None), None)
            anchor = previous if previous is not None else following if following is not None else 0
            changes[change_index] = replace(change, left_offset=anchor, left_end=anchor)
        else:
            previous = next((right[ri].end for _, ri in reversed(pairs[:row_index]) if ri is not None), None)
            following = next((right[ri].start for _, ri in pairs[row_index + 1:] if ri is not None), None)
            anchor = previous if previous is not None else following if following is not None else 0
            changes[change_index] = replace(change, right_offset=anchor, right_end=anchor)
    return DiffResult(
        left, right, tuple(left_spans), tuple(right_spans), tuple(changes),
        tuple(alignments), tuple(pairs), len(WORD_RE.findall(left_text)), len(WORD_RE.findall(right_text)),
    )
