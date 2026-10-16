"""Historical plain-text HTML projection shared by API and runtime."""

from html.parser import HTMLParser


class PlainHTML(HTMLParser):
    """Keep button values usable from a numeric/string CLI prompt; no web rendering."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.buttons = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {'br', 'p', 'div'} and (
            not self.parts or not self.parts[-1].endswith('\n')
        ):
            self.parts.append('\n')
        if tag in {'button', 'nonbutton'}:
            val = attrs.get('value')
            self.buttons.append(val)
        if tag == 'img':
            self.parts.append(attrs.get('alt', '[image omitted]'))

    def handle_endtag(self, tag):
        if tag in {'p', 'div'}:
            self.parts.append('\n')
        if tag in {'button', 'nonbutton'} and self.buttons:
            self.buttons.pop()

    def handle_data(self, data):
        self.parts.append(data)


def html_plain(text):
    p = PlainHTML()
    p.feed(text)
    p.close()
    return ''.join(p.parts)
