"""Tests for parsing posts out of X's GraphQL responses.

The fixtures mirror the real Likes endpoint response structure (verified
by probing the API). All data is synthetic and deterministic.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

import main  # noqa: E402


def make_tweet(
    *,
    rest_id="100",
    name="Alice",
    screen_name="alice",
    created_at="Thu Jul 30 13:26:30 +0000 2026",
    full_text="hello world",
    images=("https://pbs.twimg.com/media/a.jpg",),
    wrapped=False,
):
    """Build one timeline entry with the real response shape."""
    result = {
        "__typename": "Tweet",
        "rest_id": rest_id,
        "core": {
            "user_results": {
                "result": {
                    "core": {"name": name, "screen_name": screen_name},
                },
            },
        },
        "legacy": {
            "created_at": created_at,
            "full_text": full_text,
            "extended_entities": {
                "media": [
                    {"type": "photo", "media_url_https": url} for url in images
                ],
            },
        },
    }
    if wrapped:
        result = {"__typename": "TweetWithVisibilityResults", "tweet": result}
    return {"content": {"itemContent": {"tweet_results": {"result": result}}}}


def make_response(*entries):
    """Wrap timeline entries in the real response envelope."""
    return {
        "data": {
            "user": {
                "result": {
                    "timeline": {
                        "timeline": {
                            "instructions": [
                                {"type": "TimelineAddEntries", "entries": list(entries)},
                            ],
                        },
                    },
                },
            },
        },
    }


class FormatCreatedAtTest(unittest.TestCase):
    def test_converts_x_date_to_iso_8601(self):
        self.assertEqual(
            main.format_created_at("Thu Jul 30 13:26:30 +0000 2026"),
            "2026-07-30T13:26:30+00:00",
        )

    def test_unparseable_date_is_returned_as_is(self):
        self.assertEqual(main.format_created_at(""), "")
        self.assertEqual(main.format_created_at("not a date"), "not a date")


class ParsePostsTest(unittest.TestCase):
    def test_parses_post_details(self):
        data = make_response(make_tweet())

        posts = main.parse_posts(data)

        self.assertEqual(posts, [{
            "author": "Alice",
            "handle": "alice",
            "date": "2026-07-30T13:26:30+00:00",
            "text": "hello world",
            "post_url": "https://x.com/alice/status/100",
            "images": ["https://pbs.twimg.com/media/a.jpg"],
        }])

    def test_multi_image_post_yields_one_entry_with_all_images(self):
        images = tuple(f"https://pbs.twimg.com/media/{c}.jpg" for c in "abcd")
        data = make_response(make_tweet(images=images))

        posts = main.parse_posts(data)

        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["images"], list(images))

    def test_visibility_wrapped_tweet_is_unwrapped(self):
        data = make_response(make_tweet(wrapped=True))

        posts = main.parse_posts(data)

        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["handle"], "alice")

    def test_tweet_without_media_is_skipped(self):
        entry = make_tweet()
        result = entry["content"]["itemContent"]["tweet_results"]["result"]
        del result["legacy"]["extended_entities"]
        data = make_response(entry)

        self.assertEqual(main.parse_posts(data), [])

    def test_missing_author_falls_back_to_empty_strings(self):
        entry = make_tweet()
        result = entry["content"]["itemContent"]["tweet_results"]["result"]
        del result["core"]
        data = make_response(entry)

        posts = main.parse_posts(data)

        self.assertEqual(posts[0]["author"], "")
        self.assertEqual(posts[0]["handle"], "")

    def test_multiple_tweets_yield_multiple_posts_in_order(self):
        data = make_response(
            make_tweet(rest_id="100", screen_name="alice"),
            make_tweet(rest_id="200", screen_name="bob"),
        )

        posts = main.parse_posts(data)

        self.assertEqual([p["post_url"] for p in posts], [
            "https://x.com/alice/status/100",
            "https://x.com/bob/status/200",
        ])


if __name__ == "__main__":
    unittest.main(verbosity=2)
