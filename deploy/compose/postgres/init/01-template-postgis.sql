-- deploy/compose/postgres/init/01-template-postgis.sql
-- template_postgis exactly as Arches creates it (arches/install/ubuntu_setup.sh):
-- createdb -E UTF8 -T template0 --locale=en_US.utf8, marked as a template,
-- PostGIS and uuid-ossp, the PostGIS catalogue tables granted to PUBLIC.
-- Runs once, on an empty data volume. The application database is created
-- from it by Arches' setup_db (entrypoint `init`); unaccent and btree_gist are
-- added by the Arches and arches-controlled-lists migrations.
CREATE DATABASE template_postgis TEMPLATE template0 ENCODING 'UTF8' LOCALE 'en_US.utf8';
UPDATE pg_database SET datistemplate = true WHERE datname = 'template_postgis';
\connect template_postgis
CREATE EXTENSION postgis;
CREATE EXTENSION "uuid-ossp";
GRANT ALL ON geometry_columns TO PUBLIC;
GRANT ALL ON geography_columns TO PUBLIC;
GRANT ALL ON spatial_ref_sys TO PUBLIC;
