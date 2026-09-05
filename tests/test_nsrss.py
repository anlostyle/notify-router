from plugins.nsrss.main import RSSMonitor, format_pubdate


def test_nsrss_pubdate_is_converted_from_gmt_to_beijing_time():
    assert format_pubdate("Fri, 05 Sep 2026 03:00:00 GMT") == "2026-09-05 11:00:00（北京时间）"


def test_nsrss_pubdate_keeps_unrecognised_values():
    assert format_pubdate("not-a-date") == "not-a-date"


def test_nsrss_parser_stores_beijing_time_in_notification_item():
    monitor = RSSMonitor.__new__(RSSMonitor)
    items = monitor.parse_rss(
        """<rss><channel><item><title>帖子</title><description>内容</description>
        <link>https://example.test/post/1</link><guid>1</guid>
        <pubDate>Fri, 05 Sep 2026 03:00:00 GMT</pubDate></item></channel></rss>"""
    )
    assert items[0]["pubdate"] == "2026-09-05 11:00:00（北京时间）"
