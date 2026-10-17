"""News: the Google News feed, its stories, and the daily digest.

Keep this a bare marker: ``config`` imports ``DEFAULT_FEED_URL`` from
``news.feed``, so a re-export here (``from .producer import NewsProducer``, say)
would pull the producer — and through it ``config`` — into a partially
initialised package and turn that import into a cycle.
"""
