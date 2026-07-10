-- 로컬 PostgreSQL(:5432)에 LMS MVP DB 생성 (1회 실행).
-- 사용: sudo -u postgres psql -d postgres -v ON_ERROR_STOP=1 -f database/setup_native_pg.sql

DO $$ BEGIN
  CREATE USER lms WITH PASSWORD 'lms';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

SELECT 'CREATE DATABASE lms_mvp OWNER lms'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'lms_mvp')\gexec

GRANT ALL PRIVILEGES ON DATABASE lms_mvp TO lms;
