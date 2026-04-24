import os
import pymysql

# Local development only - remove for production
if os.getenv('ENVIRONMENT') != 'production':
    pymysql.install_as_MySQLdb()
    pymysql.version_info = (2, 2, 6, 'final', 0)
