"""Keep the legacy remote TLS client; prefer mysqlclient for local MySQL.

The Windows native TLS stack can reject a legacy TiDB connection which works
with PyMySQL. Driver selection is process-wide, before Django loads MySQLdb.
"""
import os
from dotenv import load_dotenv

load_dotenv()
load_dotenv('env')
driver = os.getenv('DB_MYSQL_DRIVER', 'auto').strip().lower()
if driver not in {'auto', 'mysqlclient', 'pymysql'}:
    raise ValueError('DB_MYSQL_DRIVER debe ser auto, mysqlclient o pymysql.')
host = os.getenv('DB_HOST', '').strip().lower()
legacy_remote = bool(host and host not in {'127.0.0.1', 'localhost', '::1'})
if driver == 'pymysql' or (driver == 'auto' and legacy_remote):
    import pymysql
    pymysql.install_as_MySQLdb()
else:
    try:
        import MySQLdb
    except ImportError:
        if driver == 'mysqlclient':
            raise
        import pymysql
        pymysql.install_as_MySQLdb()
