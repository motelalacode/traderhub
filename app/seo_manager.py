import datetime
import sqlite3
from pathlib import Path


APP_TZ = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SEO_MANAGER_DB_PATH = DATA_DIR / "seo_manager.db"
SITEMAP_DIR = DATA_DIR / "sitemaps"


SEO_MANAGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS seo_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    path TEXT NOT NULL,
    domain TEXT NOT NULL,
    page_type TEXT NOT NULL,
    page_subtype TEXT,
    title TEXT,
    meta_description TEXT,
    h1 TEXT,
    canonical_url TEXT,
    robots_directive TEXT,
    index_expected TEXT NOT NULL DEFAULT 'noindex',
    index_status TEXT,
    status_code INTEGER,
    schema_type TEXT,
    sitemap_group TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    last_seen_at TEXT,
    last_checked_at TEXT,
    last_updated_at TEXT,
    health_score INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS seo_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id INTEGER NOT NULL,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    message TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    resolved_at TEXT,
    FOREIGN KEY(page_id) REFERENCES seo_pages(id)
);

CREATE TABLE IF NOT EXISTS seo_sitemaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sitemap_name TEXT NOT NULL UNIQUE,
    domain TEXT NOT NULL,
    sitemap_type TEXT NOT NULL,
    file_path TEXT,
    public_url TEXT,
    url_count INTEGER NOT NULL DEFAULT 0,
    last_generated_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    notes TEXT
);

CREATE TABLE IF NOT EXISTS seo_domain_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    path_pattern TEXT NOT NULL,
    expected_indexing TEXT NOT NULL,
    expected_canonical_domain TEXT,
    rule_label TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE(domain, path_pattern)
);

CREATE TABLE IF NOT EXISTS seo_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    check_type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    pages_scanned INTEGER NOT NULL DEFAULT 0,
    issues_found INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS seo_crawl_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_page_id INTEGER NOT NULL,
    to_page_id INTEGER,
    from_url TEXT NOT NULL,
    to_url TEXT NOT NULL,
    link_type TEXT NOT NULL DEFAULT 'internal',
    is_valid INTEGER NOT NULL DEFAULT 1,
    checked_at TEXT NOT NULL,
    FOREIGN KEY(from_page_id) REFERENCES seo_pages(id),
    FOREIGN KEY(to_page_id) REFERENCES seo_pages(id)
);

CREATE TABLE IF NOT EXISTS news_page_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id INTEGER NOT NULL UNIQUE,
    url TEXT NOT NULL,
    page_type TEXT NOT NULL,
    page_subtype TEXT,
    story_link_count INTEGER NOT NULL DEFAULT 0,
    stock_link_count INTEGER NOT NULL DEFAULT 0,
    section_count INTEGER NOT NULL DEFAULT 0,
    bullet_count INTEGER NOT NULL DEFAULT 0,
    summary_present INTEGER NOT NULL DEFAULT 0,
    fallback_active INTEGER NOT NULL DEFAULT 0,
    market_error_present INTEGER NOT NULL DEFAULT 0,
    shell_only INTEGER NOT NULL DEFAULT 0,
    checked_at TEXT NOT NULL,
    notes TEXT,
    FOREIGN KEY(page_id) REFERENCES seo_pages(id)
);
"""


def get_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(SEO_MANAGER_DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def utcnow_iso():
    return datetime.datetime.now(tz=APP_TZ).isoformat()


def init_seo_manager_db():
    conn = get_connection()
    try:
        conn.executescript(SEO_MANAGER_SCHEMA)
        existing_snapshot_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(news_page_snapshots)").fetchall()
        }
        snapshot_column_defs = {
            "stock_link_count": "INTEGER NOT NULL DEFAULT 0",
            "section_count": "INTEGER NOT NULL DEFAULT 0",
            "bullet_count": "INTEGER NOT NULL DEFAULT 0",
            "summary_present": "INTEGER NOT NULL DEFAULT 0",
            "fallback_active": "INTEGER NOT NULL DEFAULT 0",
            "market_error_present": "INTEGER NOT NULL DEFAULT 0",
            "shell_only": "INTEGER NOT NULL DEFAULT 0",
            "checked_at": "TEXT",
            "notes": "TEXT",
        }
        for column_name, column_sql in snapshot_column_defs.items():
            if column_name not in existing_snapshot_columns:
                conn.execute(
                    f"ALTER TABLE news_page_snapshots ADD COLUMN {column_name} {column_sql}"
                )
        conn.commit()
    finally:
        conn.close()


def seed_domain_rules(rule_rows):
    init_seo_manager_db()
    conn = get_connection()
    try:
        conn.executemany(
            """
            INSERT INTO seo_domain_rules (
                domain, path_pattern, expected_indexing,
                expected_canonical_domain, rule_label, active
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(domain, path_pattern) DO UPDATE SET
                expected_indexing = excluded.expected_indexing,
                expected_canonical_domain = excluded.expected_canonical_domain,
                rule_label = excluded.rule_label,
                active = excluded.active
            """,
            [
                (
                    row["domain"],
                    row["path_pattern"],
                    row["expected_indexing"],
                    row.get("expected_canonical_domain"),
                    row["rule_label"],
                    int(bool(row.get("active", True))),
                )
                for row in rule_rows
            ],
        )
        conn.commit()
        return conn.execute("SELECT COUNT(*) AS count FROM seo_domain_rules WHERE active = 1").fetchone()["count"]
    finally:
        conn.close()


def fetch_domain_rules():
    init_seo_manager_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT domain, path_pattern, expected_indexing,
                   expected_canonical_domain, rule_label, active
            FROM seo_domain_rules
            WHERE active = 1
            ORDER BY domain, path_pattern
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def start_check(check_type, notes=""):
    init_seo_manager_db()
    started_at = utcnow_iso()
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO seo_checks (check_type, started_at, status, notes)
            VALUES (?, ?, 'running', ?)
            """,
            (check_type, started_at, notes),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def finish_check(check_id, status, pages_scanned=0, issues_found=0, notes=""):
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE seo_checks
            SET completed_at = ?,
                status = ?,
                pages_scanned = ?,
                issues_found = ?,
                notes = ?
            WHERE id = ?
            """,
            (utcnow_iso(), status, pages_scanned, issues_found, notes, check_id),
        )
        conn.commit()
    finally:
        conn.close()


def close_stale_running_checks(check_type, older_than_minutes=5, status="timed_out"):
    init_seo_manager_db()
    cutoff = (datetime.datetime.now(tz=APP_TZ) - datetime.timedelta(minutes=int(older_than_minutes))).isoformat()
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            UPDATE seo_checks
            SET completed_at = ?,
                status = ?,
                notes = CASE
                    WHEN notes IS NULL OR notes = '' THEN ?
                    ELSE notes || ' | ' || ?
                END
            WHERE check_type = ?
              AND status = 'running'
              AND started_at < ?
            """,
            (
                utcnow_iso(),
                status,
                f"Auto-closed stale running check after {older_than_minutes} minutes.",
                f"Auto-closed stale running check after {older_than_minutes} minutes.",
                check_type,
                cutoff,
            ),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def upsert_seo_page(page_row):
    init_seo_manager_db()
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO seo_pages (
                url, path, domain, page_type, page_subtype,
                canonical_url, robots_directive, index_expected,
                index_status, status_code, schema_type,
                sitemap_group, is_active, last_seen_at,
                last_checked_at, last_updated_at, health_score
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                path = excluded.path,
                domain = excluded.domain,
                page_type = excluded.page_type,
                page_subtype = excluded.page_subtype,
                canonical_url = excluded.canonical_url,
                robots_directive = excluded.robots_directive,
                index_expected = excluded.index_expected,
                index_status = excluded.index_status,
                status_code = excluded.status_code,
                schema_type = excluded.schema_type,
                sitemap_group = excluded.sitemap_group,
                is_active = excluded.is_active,
                last_seen_at = excluded.last_seen_at,
                last_checked_at = excluded.last_checked_at,
                last_updated_at = excluded.last_updated_at,
                health_score = excluded.health_score
            """,
            (
                page_row["url"],
                page_row["path"],
                page_row["domain"],
                page_row["page_type"],
                page_row.get("page_subtype"),
                page_row.get("canonical_url"),
                page_row.get("robots_directive"),
                page_row["index_expected"],
                page_row.get("index_status"),
                page_row.get("status_code"),
                page_row.get("schema_type"),
                page_row.get("sitemap_group"),
                int(bool(page_row.get("is_active", True))),
                page_row.get("last_seen_at"),
                page_row.get("last_checked_at"),
                page_row.get("last_updated_at"),
                int(page_row.get("health_score", 100)),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def bulk_upsert_seo_pages(page_rows):
    init_seo_manager_db()
    conn = get_connection()
    try:
        conn.executemany(
            """
            INSERT INTO seo_pages (
                url, path, domain, page_type, page_subtype,
                canonical_url, robots_directive, index_expected,
                index_status, status_code, schema_type,
                sitemap_group, is_active, last_seen_at,
                last_checked_at, last_updated_at, health_score
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                path = excluded.path,
                domain = excluded.domain,
                page_type = excluded.page_type,
                page_subtype = excluded.page_subtype,
                canonical_url = excluded.canonical_url,
                robots_directive = excluded.robots_directive,
                index_expected = excluded.index_expected,
                index_status = excluded.index_status,
                status_code = excluded.status_code,
                schema_type = excluded.schema_type,
                sitemap_group = excluded.sitemap_group,
                is_active = excluded.is_active,
                last_seen_at = excluded.last_seen_at,
                last_checked_at = excluded.last_checked_at,
                last_updated_at = excluded.last_updated_at,
                health_score = excluded.health_score
            """,
            [
                (
                    page_row["url"],
                    page_row["path"],
                    page_row["domain"],
                    page_row["page_type"],
                    page_row.get("page_subtype"),
                    page_row.get("canonical_url"),
                    page_row.get("robots_directive"),
                    page_row["index_expected"],
                    page_row.get("index_status"),
                    page_row.get("status_code"),
                    page_row.get("schema_type"),
                    page_row.get("sitemap_group"),
                    int(bool(page_row.get("is_active", True))),
                    page_row.get("last_seen_at"),
                    page_row.get("last_checked_at"),
                    page_row.get("last_updated_at"),
                    int(page_row.get("health_score", 100)),
                )
                for page_row in page_rows
            ],
        )
        conn.commit()
    finally:
        conn.close()


def mark_pages_inactive_except(seen_urls):
    init_seo_manager_db()
    conn = get_connection()
    try:
        if not seen_urls:
            conn.execute("UPDATE seo_pages SET is_active = 0")
            conn.commit()
            return

        # SQLite has a variable limit, so we reset active flags first and then
        # reactivate current inventory rows in manageable chunks.
        conn.execute("UPDATE seo_pages SET is_active = 0")
        chunk_size = 500
        for start in range(0, len(seen_urls), chunk_size):
            batch = seen_urls[start : start + chunk_size]
            placeholders = ",".join("?" for _ in batch)
            conn.execute(
                f"UPDATE seo_pages SET is_active = 1 WHERE url IN ({placeholders})",
                tuple(batch),
            )
        conn.commit()
    finally:
        conn.close()


def get_inventory_summary():
    init_seo_manager_db()
    conn = get_connection()
    try:
        total_pages = conn.execute(
            "SELECT COUNT(*) AS count FROM seo_pages WHERE is_active = 1"
        ).fetchone()["count"]
        by_domain = [
            dict(row)
            for row in conn.execute(
                """
                SELECT domain, COUNT(*) AS page_count
                FROM seo_pages
                WHERE is_active = 1
                GROUP BY domain
                ORDER BY domain
                """
            ).fetchall()
        ]
        by_type = [
            dict(row)
            for row in conn.execute(
                """
                SELECT page_type, COUNT(*) AS page_count
                FROM seo_pages
                WHERE is_active = 1
                GROUP BY page_type
                ORDER BY page_count DESC, page_type
                """
            ).fetchall()
        ]
        latest_check = conn.execute(
            """
            SELECT id, check_type, started_at, completed_at, status, pages_scanned
            FROM seo_checks
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        return {
            "db_path": str(SEO_MANAGER_DB_PATH),
            "total_pages": total_pages,
            "by_domain": by_domain,
            "by_type": by_type,
            "latest_check": dict(latest_check) if latest_check else None,
        }
    finally:
        conn.close()


def fetch_seo_pages_for_extraction(domain=None, limit=100, offset=0, only_missing=False, page_types=None):
    init_seo_manager_db()
    conn = get_connection()
    try:
        where_clauses = ["is_active = 1"]
        params = []
        if domain:
            where_clauses.append("domain = ?")
            params.append(domain)
        if only_missing:
            where_clauses.append("(title IS NULL OR meta_description IS NULL OR h1 IS NULL)")
        if page_types:
            placeholders = ",".join("?" for _ in page_types)
            where_clauses.append(f"page_type IN ({placeholders})")
            params.extend(page_types)
        where_sql = " AND ".join(where_clauses)
        rows = conn.execute(
            f"""
            SELECT id, url, path, domain, page_type, page_subtype,
                   canonical_url, robots_directive, index_expected,
                   index_status, status_code, schema_type, sitemap_group,
                   last_checked_at
            FROM seo_pages
            WHERE {where_sql}
            ORDER BY domain, path
            LIMIT ? OFFSET ?
            """,
            tuple(params + [int(limit), int(offset)]),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def update_seo_page_snapshot(page_id, snapshot):
    init_seo_manager_db()
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE seo_pages
            SET title = ?,
                meta_description = ?,
                h1 = ?,
                canonical_url = ?,
                robots_directive = ?,
                index_status = ?,
                status_code = ?,
                schema_type = ?,
                last_checked_at = ?
            WHERE id = ?
            """,
            (
                snapshot.get("title"),
                snapshot.get("meta_description"),
                snapshot.get("h1"),
                snapshot.get("canonical_url"),
                snapshot.get("robots_directive"),
                snapshot.get("index_status"),
                snapshot.get("status_code"),
                snapshot.get("schema_type"),
                snapshot.get("last_checked_at"),
                page_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def replace_page_crawl_links(page_id, from_url, links):
    init_seo_manager_db()
    checked_at = utcnow_iso()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM seo_crawl_links WHERE from_page_id = ?", (int(page_id),))
        if links:
            normalized_links = []
            unique_urls = []
            seen = set()
            for link in links:
                to_url = str(link.get("to_url") or "").strip()
                if not to_url or to_url in seen:
                    continue
                seen.add(to_url)
                unique_urls.append(to_url)
                normalized_links.append(
                    {
                        "to_url": to_url,
                        "link_type": str(link.get("link_type") or "internal").strip() or "internal",
                    }
                )

            target_map = {}
            if unique_urls:
                chunk_size = 500
                for start in range(0, len(unique_urls), chunk_size):
                    batch = unique_urls[start : start + chunk_size]
                    placeholders = ",".join("?" for _ in batch)
                    rows = conn.execute(
                        f"""
                        SELECT id, url, status_code
                        FROM seo_pages
                        WHERE is_active = 1
                          AND url IN ({placeholders})
                        """,
                        tuple(batch),
                    ).fetchall()
                    for row in rows:
                        target_map[row["url"]] = dict(row)

            conn.executemany(
                """
                INSERT INTO seo_crawl_links (
                    from_page_id, to_page_id, from_url, to_url,
                    link_type, is_valid, checked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        int(page_id),
                        (target_map.get(item["to_url"]) or {}).get("id"),
                        from_url,
                        item["to_url"],
                        item["link_type"],
                        int(
                            (
                                item["to_url"] in target_map
                                and (target_map[item["to_url"]].get("status_code") in (None, 200))
                            )
                        ),
                        checked_at,
                    )
                    for item in normalized_links
                ],
            )
        conn.commit()
        return len(links)
    finally:
        conn.close()


def get_extraction_summary():
    init_seo_manager_db()
    conn = get_connection()
    try:
        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS total_pages,
                SUM(CASE WHEN title IS NOT NULL AND TRIM(title) != '' THEN 1 ELSE 0 END) AS titled_pages,
                SUM(CASE WHEN meta_description IS NOT NULL AND TRIM(meta_description) != '' THEN 1 ELSE 0 END) AS meta_pages,
                SUM(CASE WHEN h1 IS NOT NULL AND TRIM(h1) != '' THEN 1 ELSE 0 END) AS h1_pages,
                SUM(CASE WHEN last_checked_at IS NOT NULL THEN 1 ELSE 0 END) AS checked_pages
            FROM seo_pages
            WHERE is_active = 1
            """
        ).fetchone()
        by_domain = [
            dict(row)
            for row in conn.execute(
                """
                SELECT domain,
                       COUNT(*) AS total_pages,
                       SUM(CASE WHEN title IS NOT NULL AND TRIM(title) != '' THEN 1 ELSE 0 END) AS titled_pages,
                       SUM(CASE WHEN meta_description IS NOT NULL AND TRIM(meta_description) != '' THEN 1 ELSE 0 END) AS meta_pages,
                       SUM(CASE WHEN h1 IS NOT NULL AND TRIM(h1) != '' THEN 1 ELSE 0 END) AS h1_pages
                FROM seo_pages
                WHERE is_active = 1
                GROUP BY domain
                ORDER BY domain
                """
            ).fetchall()
        ]
        latest_check = conn.execute(
            """
            SELECT id, check_type, started_at, completed_at, status, pages_scanned
            FROM seo_checks
            WHERE check_type = 'metadata_extract'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        return {
            "totals": dict(totals) if totals else {},
            "by_domain": by_domain,
            "latest_check": dict(latest_check) if latest_check else None,
        }
    finally:
        conn.close()


def count_seo_pages_for_link_scan(domain=None, page_types=None, only_checked=True, only_unlinked=False):
    init_seo_manager_db()
    conn = get_connection()
    try:
        where_clauses = ["p.is_active = 1"]
        params = []
        join_sql = ""
        if domain:
            where_clauses.append("p.domain = ?")
            params.append(domain)
        if only_checked:
            where_clauses.append("p.last_checked_at IS NOT NULL")
        if page_types:
            placeholders = ",".join("?" for _ in page_types)
            where_clauses.append(f"p.page_type IN ({placeholders})")
            params.extend(page_types)
        if only_unlinked:
            join_sql = "LEFT JOIN seo_crawl_links cl ON cl.from_page_id = p.id"
        where_sql = " AND ".join(where_clauses)
        if only_unlinked:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS page_count
                FROM (
                    SELECT p.id
                    FROM seo_pages p
                    {join_sql}
                    WHERE {where_sql}
                    GROUP BY p.id
                    HAVING COUNT(cl.id) = 0
                ) ranked
                """,
                tuple(params),
            ).fetchone()
        else:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS page_count
                FROM seo_pages p
                WHERE {where_sql}
                """,
                tuple(params),
            ).fetchone()
        return int(row["page_count"]) if row else 0
    finally:
        conn.close()


def fetch_seo_pages_for_link_scan(domain=None, limit=100, offset=0, page_types=None, only_checked=True, only_unlinked=False):
    init_seo_manager_db()
    conn = get_connection()
    try:
        where_clauses = ["p.is_active = 1"]
        params = []
        join_sql = "LEFT JOIN seo_crawl_links cl ON cl.from_page_id = p.id"
        if domain:
            where_clauses.append("p.domain = ?")
            params.append(domain)
        if only_checked:
            where_clauses.append("p.last_checked_at IS NOT NULL")
        if page_types:
            placeholders = ",".join("?" for _ in page_types)
            where_clauses.append(f"p.page_type IN ({placeholders})")
            params.extend(page_types)
        where_sql = " AND ".join(where_clauses)
        having_sql = "HAVING COUNT(cl.id) = 0" if only_unlinked else ""
        rows = conn.execute(
            f"""
            SELECT p.id, p.url, p.path, p.domain, p.page_type, p.page_subtype,
                   p.last_checked_at, p.health_score,
                   COUNT(cl.id) AS existing_link_rows
            FROM seo_pages p
            {join_sql}
            WHERE {where_sql}
            GROUP BY p.id
            {having_sql}
            ORDER BY
              CASE p.page_type
                WHEN 'sector_hub' THEN 1
                WHEN 'trend_hub' THEN 2
                WHEN 'archive_hub' THEN 3
                WHEN 'derivatives_hub' THEN 4
                WHEN 'ipo_hub' THEN 5
                WHEN 'market_news' THEN 6
                WHEN 'alerts_prep' THEN 7
                WHEN 'sector' THEN 8
                WHEN 'archive' THEN 9
                WHEN 'trend' THEN 10
                WHEN 'sector_archive' THEN 11
                WHEN 'stock' THEN 12
                WHEN 'stock_archive' THEN 13
                WHEN 'stock_news' THEN 14
                WHEN 'derivatives' THEN 15
                WHEN 'ipo_list' THEN 16
                WHEN 'ipo' THEN 17
                ELSE 99
              END,
              p.path
            LIMIT ? OFFSET ?
            """,
            tuple(params + [int(limit), int(offset)]),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def fetch_seo_pages_for_issue_detection(domain=None, limit=100, offset=0, only_checked=True, page_types=None):
    init_seo_manager_db()
    conn = get_connection()
    try:
        where_clauses = ["is_active = 1"]
        params = []
        if domain:
            where_clauses.append("domain = ?")
            params.append(domain)
        if only_checked:
            where_clauses.append("last_checked_at IS NOT NULL")
        if page_types:
            placeholders = ",".join("?" for _ in page_types)
            where_clauses.append(f"page_type IN ({placeholders})")
            params.extend(page_types)
        where_sql = " AND ".join(where_clauses)
        rows = conn.execute(
            f"""
            SELECT id, url, path, domain, page_type, page_subtype,
                   title, meta_description, h1, canonical_url,
                   robots_directive, index_expected, index_status,
                   status_code, schema_type, sitemap_group,
                   last_checked_at, health_score
            FROM seo_pages
            WHERE {where_sql}
            ORDER BY domain, path
            LIMIT ? OFFSET ?
            """,
            tuple(params + [int(limit), int(offset)]),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def fetch_seo_page_by_url(url):
    init_seo_manager_db()
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT id, url, path, domain, page_type, page_subtype,
                   title, meta_description, h1, canonical_url,
                   robots_directive, index_expected, index_status,
                   status_code, schema_type, sitemap_group,
                   last_checked_at, health_score
            FROM seo_pages
            WHERE url = ?
            LIMIT 1
            """,
            (url,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def replace_page_issues(issue_map):
    init_seo_manager_db()
    conn = get_connection()
    try:
        page_ids = [int(page_id) for page_id in issue_map.keys()]
        if page_ids:
            placeholders = ",".join("?" for _ in page_ids)
            conn.execute(
                f"DELETE FROM seo_issues WHERE page_id IN ({placeholders}) AND status = 'active'",
                tuple(page_ids),
            )
        issue_rows = []
        for page_id, issues in issue_map.items():
            for issue in issues:
                issue_rows.append(
                    (
                        int(page_id),
                        issue["issue_type"],
                        issue["severity"],
                        "active",
                        issue["message"],
                        issue["detected_at"],
                        None,
                    )
                )
        if issue_rows:
            conn.executemany(
                """
                INSERT INTO seo_issues (
                    page_id, issue_type, severity, status, message, detected_at, resolved_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                issue_rows,
            )
        conn.commit()
        return len(issue_rows)
    finally:
        conn.close()


def recompute_health_scores(page_ids=None):
    init_seo_manager_db()
    conn = get_connection()
    try:
        params = []
        if page_ids:
            placeholders = ",".join("?" for _ in page_ids)
            page_rows = conn.execute(
                f"SELECT id FROM seo_pages WHERE id IN ({placeholders})",
                tuple(page_ids),
            ).fetchall()
        else:
            page_rows = conn.execute("SELECT id FROM seo_pages WHERE is_active = 1").fetchall()

        updated = 0
        for row in page_rows:
            page_id = int(row["id"])
            severity_rows = conn.execute(
                """
                SELECT severity, COUNT(*) AS issue_count
                FROM seo_issues
                WHERE page_id = ? AND status = 'active'
                GROUP BY severity
                """,
                (page_id,),
            ).fetchall()
            score = 100
            for sev_row in severity_rows:
                severity = sev_row["severity"]
                count = int(sev_row["issue_count"])
                if severity == "high":
                    score -= 20 * count
                elif severity == "medium":
                    score -= 10 * count
                else:
                    score -= 5 * count
            score = max(0, score)
            conn.execute(
                "UPDATE seo_pages SET health_score = ? WHERE id = ?",
                (score, page_id),
            )
            updated += 1
        conn.commit()
        return updated
    finally:
        conn.close()


def get_issue_summary():
    init_seo_manager_db()
    conn = get_connection()
    try:
        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS active_issues,
                COUNT(DISTINCT page_id) AS issue_pages,
                SUM(CASE WHEN severity = 'high' THEN 1 ELSE 0 END) AS high_severity,
                SUM(CASE WHEN severity = 'medium' THEN 1 ELSE 0 END) AS medium_severity,
                SUM(CASE WHEN severity = 'low' THEN 1 ELSE 0 END) AS low_severity
            FROM seo_issues
            WHERE status = 'active'
            """
        ).fetchone()
        by_type = [
            dict(row)
            for row in conn.execute(
                """
                SELECT issue_type, severity, COUNT(*) AS issue_count
                FROM seo_issues
                WHERE status = 'active'
                GROUP BY issue_type, severity
                ORDER BY issue_count DESC, issue_type
                """
            ).fetchall()
        ]
        latest_check = conn.execute(
            """
            SELECT id, check_type, started_at, completed_at, status, pages_scanned, issues_found
            FROM seo_checks
            WHERE check_type = 'issue_detect'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        lowest_health = [
            dict(row)
            for row in conn.execute(
                """
                SELECT url, domain, page_type, health_score
                FROM seo_pages
                WHERE is_active = 1
                ORDER BY health_score ASC, domain, path
                LIMIT 20
                """
            ).fetchall()
        ]
        return {
            "totals": dict(totals) if totals else {},
            "by_type": by_type,
            "latest_check": dict(latest_check) if latest_check else None,
            "lowest_health": lowest_health,
        }
    finally:
        conn.close()


def list_seo_issues(limit=100, severity=None, issue_type=None, domain=None):
    init_seo_manager_db()
    conn = get_connection()
    try:
        where_clauses = ["i.status = 'active'"]
        params = []
        if severity:
            where_clauses.append("i.severity = ?")
            params.append(severity)
        if issue_type:
            where_clauses.append("i.issue_type = ?")
            params.append(issue_type)
        if domain:
            where_clauses.append("p.domain = ?")
            params.append(domain)
        where_sql = " AND ".join(where_clauses)
        rows = conn.execute(
            f"""
            SELECT i.id, i.issue_type, i.severity, i.message, i.detected_at,
                   p.url, p.domain, p.page_type, p.page_subtype, p.health_score
            FROM seo_issues i
            JOIN seo_pages p ON p.id = i.page_id
            WHERE {where_sql}
            ORDER BY
              CASE i.severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
              i.detected_at DESC,
              p.domain,
              p.path
            LIMIT ?
            """,
            tuple(params + [int(limit)]),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def fetch_active_issue_pages(issue_type=None, limit=50):
    init_seo_manager_db()
    conn = get_connection()
    try:
        where_clauses = ["i.status = 'active'"]
        params = []
        if issue_type:
            where_clauses.append("i.issue_type = ?")
            params.append(issue_type)
        where_sql = " AND ".join(where_clauses)
        rows = conn.execute(
            f"""
            SELECT DISTINCT p.id, p.url, p.path, p.domain, p.page_type, p.page_subtype,
                            p.canonical_url, p.robots_directive, p.index_expected,
                            p.index_status, p.status_code, p.schema_type, p.sitemap_group,
                            p.last_checked_at, p.health_score
            FROM seo_issues i
            JOIN seo_pages p ON p.id = i.page_id
            WHERE {where_sql}
            ORDER BY p.domain, p.path
            LIMIT ?
            """,
            tuple(params + [int(limit)]),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def fetch_sitemap_eligible_pages():
    init_seo_manager_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT url, path, domain, sitemap_group, last_checked_at
            FROM seo_pages
            WHERE is_active = 1
              AND domain = 'traderhub.in'
              AND sitemap_group IS NOT NULL
              AND TRIM(sitemap_group) != ''
              AND index_expected = 'index'
              AND COALESCE(index_status, 'index') = 'index'
              AND COALESCE(status_code, 200) = 200
            ORDER BY sitemap_group, path
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def replace_sitemap_records(sitemap_rows):
    init_seo_manager_db()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM seo_sitemaps")
        if sitemap_rows:
            conn.executemany(
                """
                INSERT INTO seo_sitemaps (
                    sitemap_name, domain, sitemap_type, file_path, public_url,
                    url_count, last_generated_at, status, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["sitemap_name"],
                        row["domain"],
                        row["sitemap_type"],
                        row.get("file_path"),
                        row.get("public_url"),
                        int(row.get("url_count", 0)),
                        row.get("last_generated_at"),
                        row.get("status", "completed"),
                        row.get("notes", ""),
                    )
                    for row in sitemap_rows
                ],
            )
        conn.commit()
        return len(sitemap_rows)
    finally:
        conn.close()


def get_dashboard_overview():
    init_seo_manager_db()
    conn = get_connection()
    try:
        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS total_pages,
                SUM(CASE WHEN domain = 'traderhub.in' AND index_expected = 'index' THEN 1 ELSE 0 END) AS public_indexable_pages,
                SUM(CASE WHEN health_score < 100 THEN 1 ELSE 0 END) AS pages_with_issues
            FROM seo_pages
            WHERE is_active = 1
            """
        ).fetchone()
        issue_totals = conn.execute(
            """
            SELECT
                COUNT(*) AS active_issues,
                SUM(CASE WHEN severity = 'high' THEN 1 ELSE 0 END) AS high_severity_issues
            FROM seo_issues
            WHERE status = 'active'
            """
        ).fetchone()
        duplicate_meta_count = conn.execute(
            """
            SELECT COUNT(*) AS duplicate_groups
            FROM (
                SELECT meta_description
                FROM seo_pages
                WHERE is_active = 1
                  AND meta_description IS NOT NULL
                  AND TRIM(meta_description) != ''
                GROUP BY meta_description
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()["duplicate_groups"]
        domain_health = [
            dict(row)
            for row in conn.execute(
                """
                SELECT domain,
                       COUNT(*) AS total_pages,
                       SUM(CASE WHEN index_expected = 'index' THEN 1 ELSE 0 END) AS expected_indexable,
                       SUM(CASE WHEN index_status = 'index' THEN 1 ELSE 0 END) AS actual_indexable,
                       SUM(CASE WHEN health_score < 100 THEN 1 ELSE 0 END) AS issue_pages
                FROM seo_pages
                WHERE is_active = 1
                GROUP BY domain
                ORDER BY domain
                """
            ).fetchall()
        ]
        page_type_breakdown = [
            dict(row)
            for row in conn.execute(
                """
                SELECT page_type, COUNT(*) AS page_count
                FROM seo_pages
                WHERE is_active = 1
                GROUP BY page_type
                ORDER BY page_count DESC, page_type
                """
            ).fetchall()
        ]
        recent_checks = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, check_type, started_at, completed_at, status, pages_scanned, issues_found
                FROM seo_checks
                ORDER BY id DESC
                LIMIT 10
                """
            ).fetchall()
        ]
        urgent_issues = [
            dict(row)
            for row in conn.execute(
                """
                SELECT i.issue_type, i.severity, i.message, i.detected_at, p.url, p.domain, p.page_type
                FROM seo_issues i
                JOIN seo_pages p ON p.id = i.page_id
                WHERE i.status = 'active' AND i.severity = 'high'
                ORDER BY i.detected_at DESC
                LIMIT 20
                """
            ).fetchall()
        ]
        sitemap_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT sitemap_name, sitemap_type, url_count, last_generated_at, status
                FROM seo_sitemaps
                ORDER BY sitemap_type, sitemap_name
                """
            ).fetchall()
        ]
        return {
            "totals": {**dict(totals), **dict(issue_totals), "duplicate_meta_groups": duplicate_meta_count},
            "domain_health": domain_health,
            "page_type_breakdown": page_type_breakdown,
            "recent_checks": recent_checks,
            "urgent_issues": urgent_issues,
            "sitemaps": sitemap_rows,
        }
    finally:
        conn.close()


def list_seo_pages(limit=100, offset=0, domain=None, page_type=None, issue_only=False):
    init_seo_manager_db()
    conn = get_connection()
    try:
        where_clauses = ["p.is_active = 1"]
        params = []
        if domain:
            where_clauses.append("p.domain = ?")
            params.append(domain)
        if page_type:
            where_clauses.append("p.page_type = ?")
            params.append(page_type)
        if issue_only:
            where_clauses.append("p.health_score < 100")
        where_sql = " AND ".join(where_clauses)
        rows = conn.execute(
            f"""
            SELECT p.id, p.url, p.domain, p.page_type, p.page_subtype,
                   p.title, p.meta_description, p.h1, p.canonical_url,
                   p.index_status, p.sitemap_group, p.health_score,
                   p.last_checked_at,
                   COUNT(i.id) AS active_issue_count
            FROM seo_pages p
            LEFT JOIN seo_issues i
              ON i.page_id = p.id AND i.status = 'active'
            WHERE {where_sql}
            GROUP BY p.id
            ORDER BY p.health_score ASC, p.domain, p.path
            LIMIT ? OFFSET ?
            """,
            tuple(params + [int(limit), int(offset)]),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_indexing_policy_summary(limit=100, domain=None):
    init_seo_manager_db()
    conn = get_connection()
    try:
        where_clauses = ["p.is_active = 1"]
        params = []
        if domain:
            where_clauses.append("p.domain = ?")
            params.append(domain)
        where_sql = " AND ".join(where_clauses)
        mismatches = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT p.url, p.domain, p.page_type, p.index_expected, p.index_status,
                       p.canonical_url
                FROM seo_pages p
                WHERE {where_sql}
                  AND (
                    p.index_expected != p.index_status
                    OR (p.domain = 'traderhub.in' AND (p.canonical_url IS NULL OR p.canonical_url NOT LIKE 'https://traderhub.in%'))
                  )
                ORDER BY p.domain, p.path
                LIMIT ?
                """,
                tuple(params + [int(limit)]),
            ).fetchall()
        ]
        domain_rules = [
            dict(row)
            for row in conn.execute(
                """
                SELECT domain, path_pattern, expected_indexing, expected_canonical_domain, rule_label, active
                FROM seo_domain_rules
                WHERE active = 1
                ORDER BY domain, path_pattern
                """
            ).fetchall()
        ]
        return {"mismatches": mismatches, "domain_rules": domain_rules}
    finally:
        conn.close()


def get_sitemaps_overview():
    init_seo_manager_db()
    conn = get_connection()
    try:
        sitemap_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT sitemap_name, domain, sitemap_type, public_url, url_count, last_generated_at, status, notes
                FROM seo_sitemaps
                ORDER BY sitemap_type, sitemap_name
                """
            ).fetchall()
        ]
        return {"rows": sitemap_rows}
    finally:
        conn.close()


def get_metadata_overview(limit=100):
    init_seo_manager_db()
    conn = get_connection()
    try:
        issue_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT i.issue_type, i.severity, i.message, p.url, p.page_type,
                       p.title, p.meta_description, p.h1, p.canonical_url
                FROM seo_issues i
                JOIN seo_pages p ON p.id = i.page_id
                WHERE i.status = 'active'
                  AND i.issue_type IN (
                    'missing_title',
                    'missing_meta_description',
                    'missing_h1',
                    'missing_canonical',
                    'canonical_mismatch'
                  )
                ORDER BY
                  CASE i.severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                  p.domain, p.path
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        ]
        duplicates = [
            dict(row)
            for row in conn.execute(
                """
                SELECT meta_description, COUNT(*) AS page_count
                FROM seo_pages
                WHERE is_active = 1
                  AND meta_description IS NOT NULL
                  AND TRIM(meta_description) != ''
                GROUP BY meta_description
                HAVING COUNT(*) > 1
                ORDER BY page_count DESC, meta_description
                LIMIT 20
                """
            ).fetchall()
        ]
        return {"issues": issue_rows, "duplicate_meta_groups": duplicates}
    finally:
        conn.close()


def get_crawlability_overview(limit=100):
    init_seo_manager_db()
    conn = get_connection()
    try:
        non_200_pages = [
            dict(row)
            for row in conn.execute(
                """
                SELECT url, domain, page_type, page_subtype, status_code, health_score, last_checked_at
                FROM seo_pages
                WHERE is_active = 1
                  AND domain = 'traderhub.in'
                  AND status_code IS NOT NULL
                  AND status_code != 200
                ORDER BY status_code, path
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        ]
        indexing_conflicts = [
            dict(row)
            for row in conn.execute(
                """
                SELECT url, domain, page_type, page_subtype, index_expected, index_status, health_score
                FROM seo_pages
                WHERE is_active = 1
                  AND domain = 'traderhub.in'
                  AND index_expected = 'index'
                  AND COALESCE(index_status, 'index') != 'index'
                ORDER BY path
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        ]
        unchecked_public_pages = [
            dict(row)
            for row in conn.execute(
                """
                SELECT url, domain, page_type, page_subtype, health_score
                FROM seo_pages
                WHERE is_active = 1
                  AND domain = 'traderhub.in'
                  AND index_expected = 'index'
                  AND last_checked_at IS NULL
                ORDER BY path
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        ]
        broken_internal_links = [
            dict(row)
            for row in conn.execute(
                """
                SELECT cl.from_url, cl.to_url, cl.link_type, cl.checked_at,
                       sp.page_type AS from_page_type, sp.page_subtype AS from_page_subtype,
                       tp.page_type AS target_page_type, tp.page_subtype AS target_page_subtype,
                       tp.status_code AS target_status_code,
                       COALESCE(tp.health_score, 100) AS target_health_score
                FROM seo_crawl_links cl
                JOIN seo_pages sp ON sp.id = cl.from_page_id
                LEFT JOIN seo_pages tp ON tp.url = cl.to_url AND tp.is_active = 1
                WHERE sp.is_active = 1
                  AND sp.domain = 'traderhub.in'
                  AND tp.id IS NOT NULL
                  AND tp.domain = 'traderhub.in'
                  AND tp.index_expected = 'index'
                  AND tp.status_code IS NOT NULL
                  AND tp.status_code != 200
                ORDER BY cl.checked_at DESC, cl.from_url, cl.to_url
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        ]
        orphan_pages = [
            dict(row)
            for row in conn.execute(
                """
                SELECT p.url, p.domain, p.page_type, p.page_subtype,
                       p.health_score, p.last_checked_at
                FROM seo_pages p
                LEFT JOIN seo_crawl_links cl
                  ON cl.to_url = p.url
                LEFT JOIN seo_pages sp
                  ON sp.id = cl.from_page_id
                 AND sp.is_active = 1
                 AND sp.domain = 'traderhub.in'
                WHERE p.is_active = 1
                  AND p.domain = 'traderhub.in'
                  AND p.index_expected = 'index'
                  AND p.last_checked_at IS NOT NULL
                  AND p.page_type NOT IN (
                    'ipo_hub',
                    'sector_hub',
                    'trend_hub',
                    'archive_hub',
                    'derivatives_hub',
                    'stock',
                    'stock_archive',
                    'stock_news'
                  )
                GROUP BY p.id
                HAVING COUNT(sp.id) = 0
                ORDER BY p.path
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        ]
        totals = conn.execute(
            """
            SELECT
                SUM(CASE WHEN domain = 'traderhub.in' AND index_expected = 'index' THEN 1 ELSE 0 END) AS public_pages,
                SUM(CASE WHEN domain = 'traderhub.in' AND index_expected = 'index' AND last_checked_at IS NOT NULL THEN 1 ELSE 0 END) AS checked_public_pages,
                SUM(CASE WHEN domain = 'traderhub.in' AND status_code IS NOT NULL AND status_code != 200 THEN 1 ELSE 0 END) AS non_200_count,
                SUM(CASE WHEN domain = 'traderhub.in' AND index_expected = 'index' AND COALESCE(index_status, 'index') != 'index' THEN 1 ELSE 0 END) AS indexing_conflict_count
            FROM seo_pages
            WHERE is_active = 1
            """
        ).fetchone()
        linked_totals = conn.execute(
            """
            SELECT
                COUNT(*) AS crawl_link_count,
                COUNT(DISTINCT from_page_id) AS linked_source_pages
            FROM seo_crawl_links
            """
        ).fetchone()
        return {
            "totals": dict(totals) if totals else {},
            "crawl_totals": dict(linked_totals) if linked_totals else {},
            "non_200_pages": non_200_pages,
            "indexing_conflicts": indexing_conflicts,
            "unchecked_public_pages": unchecked_public_pages,
            "broken_internal_links": broken_internal_links,
            "orphan_pages": orphan_pages,
        }
    finally:
        conn.close()


def get_news_manager_overview(limit=100):
    init_seo_manager_db()
    conn = get_connection()
    try:
        content_page_types = (
            "market_news",
            "alerts_prep",
            "stock_news",
            "trend",
            "trend_hub",
            "archive",
            "archive_hub",
            "stock_archive",
            "sector_archive",
        )
        placeholders = ",".join("?" for _ in content_page_types)
        totals = conn.execute(
            f"""
            SELECT
                COUNT(*) AS total_pages,
                SUM(CASE WHEN page_type IN ('market_news', 'alerts_prep', 'stock_news') THEN 1 ELSE 0 END) AS live_pages,
                SUM(CASE WHEN page_type IN ('trend', 'trend_hub') THEN 1 ELSE 0 END) AS trend_pages,
                SUM(CASE WHEN page_type IN ('archive', 'archive_hub', 'stock_archive', 'sector_archive') THEN 1 ELSE 0 END) AS archive_pages,
                SUM(CASE WHEN last_checked_at IS NOT NULL THEN 1 ELSE 0 END) AS reviewed_pages,
                SUM(CASE WHEN health_score < 100 THEN 1 ELSE 0 END) AS weak_pages,
                SUM(CASE WHEN status_code IS NOT NULL AND status_code != 200 THEN 1 ELSE 0 END) AS non_200_pages
            FROM seo_pages
            WHERE is_active = 1
              AND domain = 'traderhub.in'
              AND page_type IN ({placeholders})
            """,
            content_page_types,
        ).fetchone()
        by_type = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT page_type, COUNT(*) AS page_count,
                       SUM(CASE WHEN health_score < 100 THEN 1 ELSE 0 END) AS weak_pages
                FROM seo_pages
                WHERE is_active = 1
                  AND domain = 'traderhub.in'
                  AND page_type IN ({placeholders})
                GROUP BY page_type
                ORDER BY page_count DESC, page_type
                """
                ,
                content_page_types,
            ).fetchall()
        ]
        issue_rows = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT i.issue_type, i.severity, COUNT(*) AS issue_count
                FROM seo_issues i
                JOIN seo_pages p ON p.id = i.page_id
                WHERE i.status = 'active'
                  AND p.is_active = 1
                  AND p.domain = 'traderhub.in'
                  AND p.page_type IN ({placeholders})
                GROUP BY i.issue_type, i.severity
                ORDER BY issue_count DESC, i.issue_type
                LIMIT 20
                """,
                content_page_types,
            ).fetchall()
        ]
        needs_review = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT p.url, p.page_type, p.page_subtype, p.health_score, p.status_code, p.last_checked_at,
                       COUNT(i.id) AS active_issue_count
                FROM seo_pages p
                LEFT JOIN seo_issues i
                  ON i.page_id = p.id AND i.status = 'active'
                WHERE p.is_active = 1
                  AND p.domain = 'traderhub.in'
                  AND p.page_type IN ({placeholders})
                GROUP BY p.id
                HAVING p.health_score < 100
                    OR COALESCE(p.status_code, 200) != 200
                ORDER BY p.health_score ASC, p.path
                LIMIT ?
                """,
                tuple(content_page_types) + (int(limit),),
            ).fetchall()
        ]
        latest_check = conn.execute(
            """
            SELECT id, check_type, started_at, completed_at, status, pages_scanned, issues_found
            FROM seo_checks
            WHERE check_type IN ('metadata_extract', 'issue_detect', 'crawlability_scan')
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        return {
            "totals": dict(totals) if totals else {},
            "by_type": by_type,
            "issues": issue_rows,
            "needs_review": needs_review,
            "latest_check": dict(latest_check) if latest_check else None,
        }
    finally:
        conn.close()


def list_news_manager_pages(page_types, limit=100):
    init_seo_manager_db()
    conn = get_connection()
    try:
        placeholders = ",".join("?" for _ in page_types)
        rows = conn.execute(
            f"""
            SELECT p.url, p.page_type, p.page_subtype, p.title, p.meta_description,
                   p.status_code, p.health_score, p.last_checked_at,
                   COUNT(i.id) AS active_issue_count
            FROM seo_pages p
            LEFT JOIN seo_issues i
              ON i.page_id = p.id AND i.status = 'active'
            WHERE p.is_active = 1
              AND p.domain = 'traderhub.in'
              AND p.page_type IN ({placeholders})
            GROUP BY p.id
            ORDER BY p.health_score ASC, p.path
            LIMIT ?
            """,
            tuple(page_types) + (int(limit),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def fetch_news_pages_for_snapshot_scan(domain=None, limit=100, offset=0, page_types=None, only_missing=False):
    init_seo_manager_db()
    conn = get_connection()
    try:
        selected_page_types = tuple(
            page_types
            or (
                "market_news",
                "alerts_prep",
                "stock_news",
                "trend",
                "archive",
                "stock_archive",
                "sector_archive",
            )
        )
        placeholders = ",".join("?" for _ in selected_page_types)
        joins = [
            "FROM seo_pages p",
            "LEFT JOIN news_page_snapshots nps ON nps.page_id = p.id",
        ]
        where = [
            "p.is_active = 1",
            "p.page_type IN (" + placeholders + ")",
        ]
        params = list(selected_page_types)
        if domain:
            where.append("p.domain = ?")
            params.append(domain)
        if only_missing:
            where.append("nps.page_id IS NULL")
        params.extend([int(limit), int(offset)])
        rows = conn.execute(
            f"""
            SELECT p.id, p.url, p.path, p.domain, p.page_type, p.page_subtype,
                   p.title, p.meta_description, p.h1, p.status_code, p.health_score, p.last_checked_at
            {' '.join(joins)}
            WHERE {' AND '.join(where)}
            ORDER BY p.health_score ASC, p.path
            LIMIT ? OFFSET ?
            """,
            tuple(params),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def upsert_news_page_snapshot(page_row, snapshot):
    init_seo_manager_db()
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO news_page_snapshots (
                page_id, url, page_type, page_subtype, story_link_count, stock_link_count,
                section_count, bullet_count, summary_present, fallback_active,
                market_error_present, shell_only, checked_at, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(page_id) DO UPDATE SET
                url = excluded.url,
                page_type = excluded.page_type,
                page_subtype = excluded.page_subtype,
                story_link_count = excluded.story_link_count,
                stock_link_count = excluded.stock_link_count,
                section_count = excluded.section_count,
                bullet_count = excluded.bullet_count,
                summary_present = excluded.summary_present,
                fallback_active = excluded.fallback_active,
                market_error_present = excluded.market_error_present,
                shell_only = excluded.shell_only,
                checked_at = excluded.checked_at,
                notes = excluded.notes
            """,
            (
                int(page_row["id"]),
                page_row["url"],
                page_row["page_type"],
                page_row.get("page_subtype"),
                int(snapshot.get("story_link_count", 0)),
                int(snapshot.get("stock_link_count", 0)),
                int(snapshot.get("section_count", 0)),
                int(snapshot.get("bullet_count", 0)),
                int(1 if snapshot.get("summary_present") else 0),
                int(1 if snapshot.get("fallback_active") else 0),
                int(1 if snapshot.get("market_error_present") else 0),
                int(1 if snapshot.get("shell_only") else 0),
                snapshot.get("checked_at"),
                snapshot.get("notes", ""),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_news_manager_summary_overview(limit=120):
    init_seo_manager_db()
    conn = get_connection()
    try:
        summary_page_types = (
            "market_news",
            "alerts_prep",
            "stock_news",
            "trend",
            "archive",
            "stock_archive",
            "sector_archive",
        )
        placeholders = ",".join("?" for _ in summary_page_types)
        totals = conn.execute(
            f"""
            SELECT
                COUNT(*) AS total_pages,
                SUM(CASE WHEN title IS NOT NULL AND TRIM(title) != '' THEN 1 ELSE 0 END) AS titled_pages,
                SUM(CASE WHEN meta_description IS NOT NULL AND TRIM(meta_description) != '' THEN 1 ELSE 0 END) AS meta_pages,
                SUM(CASE WHEN h1 IS NOT NULL AND TRIM(h1) != '' THEN 1 ELSE 0 END) AS h1_pages,
                SUM(CASE WHEN canonical_url IS NOT NULL AND TRIM(canonical_url) != '' THEN 1 ELSE 0 END) AS canonical_pages,
                SUM(CASE WHEN status_code = 200 THEN 1 ELSE 0 END) AS ok_pages,
                SUM(CASE WHEN health_score = 100 THEN 1 ELSE 0 END) AS clean_pages,
                SUM(CASE WHEN nps.page_id IS NOT NULL THEN 1 ELSE 0 END) AS snapshot_pages,
                SUM(CASE WHEN nps.summary_present = 1 THEN 1 ELSE 0 END) AS summary_pages,
                SUM(CASE WHEN nps.fallback_active = 1 THEN 1 ELSE 0 END) AS fallback_pages,
                SUM(CASE WHEN nps.market_error_present = 1 THEN 1 ELSE 0 END) AS market_error_pages,
                SUM(CASE WHEN nps.shell_only = 1 THEN 1 ELSE 0 END) AS shell_pages
            FROM seo_pages
            LEFT JOIN news_page_snapshots nps ON nps.page_id = seo_pages.id
            WHERE is_active = 1
              AND domain = 'traderhub.in'
              AND page_type IN ({placeholders})
            """,
            summary_page_types,
        ).fetchone()
        by_type = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT
                    p.page_type,
                    COUNT(*) AS page_count,
                    SUM(CASE WHEN p.title IS NOT NULL AND TRIM(p.title) != '' THEN 1 ELSE 0 END) AS titled_pages,
                    SUM(CASE WHEN p.meta_description IS NOT NULL AND TRIM(p.meta_description) != '' THEN 1 ELSE 0 END) AS meta_pages,
                    SUM(CASE WHEN p.h1 IS NOT NULL AND TRIM(p.h1) != '' THEN 1 ELSE 0 END) AS h1_pages,
                    SUM(CASE WHEN p.health_score < 100 THEN 1 ELSE 0 END) AS weak_pages,
                    SUM(CASE WHEN nps.summary_present = 1 THEN 1 ELSE 0 END) AS summary_pages,
                    SUM(CASE WHEN nps.fallback_active = 1 THEN 1 ELSE 0 END) AS fallback_pages
                FROM seo_pages p
                LEFT JOIN news_page_snapshots nps ON nps.page_id = p.id
                WHERE p.is_active = 1
                  AND p.domain = 'traderhub.in'
                  AND p.page_type IN ({placeholders})
                GROUP BY p.page_type
                ORDER BY page_count DESC, p.page_type
                """,
                summary_page_types,
            ).fetchall()
        ]
        rows = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT p.url, p.page_type, p.page_subtype, p.title, p.meta_description, p.h1,
                       p.canonical_url, p.status_code, p.health_score, p.last_checked_at,
                       nps.story_link_count, nps.stock_link_count, nps.section_count, nps.bullet_count,
                       nps.summary_present, nps.fallback_active, nps.market_error_present,
                       nps.shell_only, nps.checked_at AS snapshot_checked_at,
                       COUNT(i.id) AS active_issue_count
                FROM seo_pages p
                LEFT JOIN news_page_snapshots nps ON nps.page_id = p.id
                LEFT JOIN seo_issues i
                  ON i.page_id = p.id AND i.status = 'active'
                WHERE p.is_active = 1
                  AND p.domain = 'traderhub.in'
                  AND p.page_type IN ({placeholders})
                GROUP BY p.id
                ORDER BY
                  CASE WHEN p.health_score < 100 THEN 0 ELSE 1 END,
                  CASE WHEN nps.page_id IS NULL THEN 0 ELSE 1 END,
                  CASE WHEN p.meta_description IS NULL OR TRIM(p.meta_description) = '' THEN 0 ELSE 1 END,
                  CASE WHEN p.h1 IS NULL OR TRIM(p.h1) = '' THEN 0 ELSE 1 END,
                  p.path
                LIMIT ?
                """,
                tuple(summary_page_types) + (int(limit),),
            ).fetchall()
        ]
        return {
            "totals": dict(totals) if totals else {},
            "by_type": by_type,
            "rows": rows,
        }
    finally:
        conn.close()


def get_news_snapshot_run_summary():
    init_seo_manager_db()
    close_stale_running_checks("news_snapshot_scan", older_than_minutes=3, status="timed_out")
    conn = get_connection()
    try:
        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS snapshot_pages,
                SUM(CASE WHEN summary_present = 1 THEN 1 ELSE 0 END) AS summary_pages,
                SUM(CASE WHEN fallback_active = 1 THEN 1 ELSE 0 END) AS fallback_pages,
                SUM(CASE WHEN market_error_present = 1 THEN 1 ELSE 0 END) AS market_error_pages,
                SUM(CASE WHEN shell_only = 1 THEN 1 ELSE 0 END) AS shell_pages
            FROM news_page_snapshots
            """
        ).fetchone()
        by_type = [
            dict(row)
            for row in conn.execute(
                """
                SELECT page_type, COUNT(*) AS page_count,
                       SUM(CASE WHEN summary_present = 1 THEN 1 ELSE 0 END) AS summary_pages,
                       SUM(CASE WHEN fallback_active = 1 THEN 1 ELSE 0 END) AS fallback_pages,
                       SUM(CASE WHEN shell_only = 1 THEN 1 ELSE 0 END) AS shell_pages
                FROM news_page_snapshots
                GROUP BY page_type
                ORDER BY page_count DESC, page_type
                """
            ).fetchall()
        ]
        latest_check = conn.execute(
            """
            SELECT id, check_type, started_at, completed_at, status, pages_scanned
            FROM seo_checks
            WHERE check_type = 'news_snapshot_scan'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        return {
            "totals": dict(totals) if totals else {},
            "by_type": by_type,
            "latest_check": dict(latest_check) if latest_check else None,
        }
    finally:
        conn.close()
