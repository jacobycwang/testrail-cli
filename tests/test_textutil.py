from tr.textutil import html_to_text

OBSERVED = (
    "<p>1. Request an inline API ... (e.g. GET /companies/{companyId})</p>"
    "<p>2. Check the resonpse http status</p>"
)


def test_consecutive_paragraphs_become_single_newlines():
    assert html_to_text(OBSERVED) == (
        "1. Request an inline API ... (e.g. GET /companies/{companyId})\n"
        "2. Check the resonpse http status"
    )


def test_entities_are_unescaped():
    html = "<p>Send &amp; verify &lt;payload&gt;&nbsp;&mdash; expect &quot;409&quot;</p>"
    assert html_to_text(html) == 'Send & verify <payload> — expect "409"'


def test_list_items_become_dash_bullets():
    html = "<ul><li>Seed 37 bookings</li><li>Disable the LINE channel</li></ul>"
    assert html_to_text(html) == "- Seed 37 bookings\n- Disable the LINE channel"


def test_inline_tags_are_dropped_but_their_text_kept():
    html = "<p><b>Given</b> a <i>seated</i> table with <code>partySize=6</code></p>"
    assert html_to_text(html) == "Given a seated table with partySize=6"


def test_anchor_keeps_href_only_when_it_differs_from_the_text():
    same = '<p><a href="https://tr.example/C482">https://tr.example/C482</a></p>'
    differs = '<p>See <a href="https://tr.example/C482">case 482</a></p>'
    assert html_to_text(same) == "https://tr.example/C482"
    assert html_to_text(differs) == "See case 482 (https://tr.example/C482)"


def test_headings_divs_and_breaks_split_lines():
    html = "<h3>Refund flow</h3><div>Open the deposit</div><p>Hit Refund<br>Confirm</p>"
    assert html_to_text(html) == "Refund flow\nOpen the deposit\nHit Refund\nConfirm"


def test_pre_blocks_keep_their_inner_text_verbatim():
    html = "<p>Payload</p><pre>{\n    \"amount\": 480,\n    \"currency\": \"TWD\"\n}</pre>"
    assert html_to_text(html) == 'Payload\n{\n    "amount": 480,\n    "currency": "TWD"\n}'


def test_three_or_more_newlines_collapse_to_two():
    assert html_to_text("<pre>alpha\n\n\n\ndelta</pre>") == "alpha\n\ndelta"


def test_trailing_whitespace_is_stripped_per_line():
    assert html_to_text("<pre>alpha   \n   delta   </pre>") == "alpha\n   delta"


def test_plain_text_passes_through_unchanged():
    plain = "1. Seed 23 bookings\r\n2. Wait 45 seconds\n3. Assert count < 5 & retry"
    assert html_to_text(plain) == (
        "1. Seed 23 bookings\n2. Wait 45 seconds\n3. Assert count < 5 & retry"
    )


def test_none_becomes_an_empty_string():
    assert html_to_text(None) == ""
    assert html_to_text("") == ""


def test_table_rows_split_lines_and_cells_stay_on_one_line():
    html = (
        "<table><tr><td>Taipei</td><td>19:30</td></tr>"
        "<tr><td>Tainan</td><td>21:00</td></tr></table>"
    )
    assert html_to_text(html) == "Taipei 19:30\nTainan 21:00"
