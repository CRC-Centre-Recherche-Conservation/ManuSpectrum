-- Data version of the Explorer's memos: every writing statement on a table
-- the Explorer reads leaves one row per transaction in `ms_data_change`, and
-- `(count(*), max(seq))` names the committed state. A second statement of the
-- same transaction gives its row a new `seq`, so a reader inside that
-- transaction sees the version move too. One row per transaction, not a
-- counter row: two writing transactions never wait on each other here.
--
-- A trigger is created only on the tables that exist when this runs.

CREATE TABLE IF NOT EXISTS ms_data_change (
    seq bigserial PRIMARY KEY,
    txid bigint NOT NULL UNIQUE,
    at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION ms_data_change() RETURNS trigger
LANGUAGE plpgsql AS $body$
BEGIN
    INSERT INTO ms_data_change (txid) VALUES (txid_current())
    ON CONFLICT (txid) DO UPDATE
        SET seq = nextval('ms_data_change_seq_seq'), at = now();
    RETURN NULL;
END
$body$;

DO $do$
DECLARE
    watched text;
BEGIN
    FOREACH watched IN ARRAY ARRAY[@@TABLES@@] LOOP
        IF to_regclass(watched) IS NOT NULL THEN
            EXECUTE format('DROP TRIGGER IF EXISTS ms_data_change ON %I', watched);
            EXECUTE format(
                'CREATE TRIGGER ms_data_change'
                ' AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON %I'
                ' FOR EACH STATEMENT EXECUTE FUNCTION ms_data_change()',
                watched
            );
        END IF;
    END LOOP;
END
$do$;
