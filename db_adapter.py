import os
import re

def patch_sqlite_for_database_url(sqlite3_module):
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return

    import psycopg2
    import psycopg2.extras

    class CursorWrapper:
        def __init__(self, cur):
            self.cur = cur
            self.lastrowid = None

        @property
        def description(self):
            return self.cur.description

        def _convert_sql(self, sql):
            sql = str(sql)

            m = re.match(r"\s*PRAGMA\s+table_info\((\w+)\)", sql, re.I)
            if m:
                table = m.group(1)
                return """
                    SELECT
                        ordinal_position - 1 AS cid,
                        column_name AS name,
                        data_type AS type,
                        CASE WHEN is_nullable='NO' THEN 1 ELSE 0 END AS notnull,
                        column_default AS dflt_value,
                        0 AS pk
                    FROM information_schema.columns
                    WHERE table_name = %s
                    ORDER BY ordinal_position
                """, (table,)

            sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
            sql = sql.replace("DATETIME", "TIMESTAMP")
            sql = sql.replace("?", "%s")
            return sql, None

        def execute(self, sql, params=None):
            sql, forced_params = self._convert_sql(sql)
            if forced_params is not None:
                params = forced_params

            sql_strip = sql.strip().lower()
            needs_returning = (
                sql_strip.startswith("insert into users")
                or sql_strip.startswith("insert into companies")
            ) and "returning id" not in sql_strip

            if needs_returning:
                sql = sql.rstrip().rstrip(";") + " RETURNING id"

            self.cur.execute(sql, params or ())

            if needs_returning:
                row = self.cur.fetchone()
                self.lastrowid = row[0] if row else None

            return self

        def fetchone(self):
            return self.cur.fetchone()

        def fetchall(self):
            return self.cur.fetchall()

        def __iter__(self):
            return iter(self.cur)

        def close(self):
            return self.cur.close()

    class ConnectionWrapper:
        row_factory = None

        def __init__(self):
            self.conn = psycopg2.connect(database_url, sslmode="require")

        def cursor(self):
            return CursorWrapper(self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor))

        def commit(self):
            return self.conn.commit()

        def rollback(self):
            return self.conn.rollback()

        def close(self):
            return self.conn.close()

    def connect(_db=None, *args, **kwargs):
        return ConnectionWrapper()

    sqlite3_module.connect = connect
