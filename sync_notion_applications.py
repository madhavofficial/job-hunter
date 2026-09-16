"""Sync applied applications between Notion Off-Campus Job Applications Tracker and jobs.db."""

import db
import notion_sync


def sync_notion() -> dict:
    db.init_db()
    return notion_sync.sync_two_way()


if __name__ == "__main__":
    sync_notion()
