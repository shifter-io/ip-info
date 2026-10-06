"""Reject corrupted public copy while preserving correctly encoded punctuation."""
import re
from html.parser import HTMLParser

CORRUPTION = re.compile(
    r'\ufffd|[\u0080-\u009f]|\u00c3[\u0080-\u00bf]|\u00c2[\u0080-\u00bf]'
    r'|\u00e2(?:\u20ac|\u0080)|\u00f0\u0178'
    r'|[\u200b\ufeff\u202a-\u202e\u2066-\u2069]|__cp|cpLocation'
    r'|__(?:IP_INFO_BRAND|SHIFTER_LOGO|EXAMPLES|FAQ)__', re.I)


class PublicText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.ignored += 1
        for name, value in attrs:
            if value and (name in ('alt', 'title', 'aria-label', 'placeholder') or
                          (tag == 'meta' and name == 'content')):
                self.parts.append(value)

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.ignored = max(0, self.ignored - 1)

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def assert_clean_html(source, label):
    parser = PublicText()
    parser.feed(source)
    for part in parser.parts:
        if CORRUPTION.search(part):
            raise ValueError(f'{label}: corrupted public text: {part[:120]!r}')
