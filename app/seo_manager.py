import datetime
import sqlite3
from pathlib import Path


APP_TZ = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SEO_MANAGER_DB_PATH = DATA_DIR / "seo_manager.db"


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
