-- Stamp the XY viewer configuration implied by the analysis technique onto
-- every measurement file entry that carries neither `rendererConfig` nor
-- `rendererConfigSource`: either one means a curator has spoken, including
-- when they cleared the configuration. Techniques resolving to more than one
-- configuration stamp nothing.
--
-- No backslash in this file: `standard_conforming_strings` is read by the
-- session running the trigger, so a backslash would parse one way on one
-- deployment and another way on the next.

CREATE OR REPLACE FUNCTION ms_xy_stamp_file_config() RETURNS trigger
LANGUAGE plpgsql AS $body$
DECLARE
    entries jsonb := NEW.tiledata -> '@@DATA_FILE_NODE@@';
    stamped jsonb;
    resolved_config uuid;
    resolved_renderer uuid;
BEGIN
    IF jsonb_typeof(entries) IS DISTINCT FROM 'array'
       OR jsonb_array_length(entries) = 0 THEN
        RETURN NEW;
    END IF;

    -- `lax` yields no ids, rather than an error, when the technique value is
    -- not the list the reference datatype writes.
    SELECT CASE
               WHEN count(DISTINCT preset.configid) = 1
               THEN (array_agg(DISTINCT preset.configid))[1]
           END
    INTO resolved_config
    FROM tiles technique
    CROSS JOIN LATERAL jsonb_array_elements_text(
        jsonb_path_query_array(
            technique.tiledata -> '@@TECHNIQUE_NODE@@',
            'lax $[*].labels[*].list_item_id'
        )
    ) AS item_id
    JOIN (VALUES
        @@TECHNIQUE_MAP@@
    ) AS preset(technique_item_id, configid)
      -- Compared as text: a malformed id in tile data must not abort the write.
      ON preset.technique_item_id = item_id
    WHERE technique.nodegroupid = '@@TECHNIQUE_NODEGROUP@@'::uuid
      AND technique.resourceinstanceid = NEW.resourceinstanceid;

    IF resolved_config IS NULL THEN
        RETURN NEW;
    END IF;

    -- Arches matches a renderer at upload time only, so the configuration
    -- pointer is inert without one.
    SELECT rendererid INTO resolved_renderer
    FROM renderer_config
    WHERE configid = resolved_config;

    SELECT jsonb_agg(
               CASE
                   WHEN jsonb_typeof(entry) = 'object'
                    AND coalesce(entry ->> 'rendererConfig', '') = ''
                    AND coalesce(entry ->> 'rendererConfigSource', '') = ''
                    AND parsed.extension = ANY (ARRAY[@@TEXT_FORMATS@@]::text[])
                   THEN entry
                        || jsonb_build_object(
                               'rendererConfig', resolved_config::text,
                               'rendererConfigSource', 'auto'
                           )
                        || CASE
                               WHEN coalesce(entry ->> 'renderer', '') = ''
                                    AND resolved_renderer IS NOT NULL
                               THEN jsonb_build_object('renderer', resolved_renderer::text)
                               ELSE '{}'::jsonb
                           END
                   ELSE entry
               END
               ORDER BY element.idx
           )
    INTO stamped
    FROM jsonb_array_elements(entries) WITH ORDINALITY AS element(entry, idx)
    -- Same answer as Python's os.path.splitext on the basename, lower-cased:
    -- "sub/.csv" and "..csv" have no extension.
    CROSS JOIN LATERAL (
        SELECT split_part(coalesce(entry ->> 'name', ''), '/', -1) AS base
    ) AS named
    CROSS JOIN LATERAL (
        SELECT CASE
                   WHEN strpos(btrim(named.base, '.'), '.') = 0 THEN ''
                   ELSE lower(split_part(named.base, '.', -1))
               END AS extension
    ) AS parsed;

    -- jsonb_set is strict: a NULL here would blank the whole tile.
    IF stamped IS DISTINCT FROM entries THEN
        NEW.tiledata := jsonb_set(NEW.tiledata, ARRAY['@@DATA_FILE_NODE@@'], stamped);
    END IF;

    RETURN NEW;
END
$body$;

DROP TRIGGER IF EXISTS ms_xy_stamp_file_config ON tiles;
CREATE TRIGGER ms_xy_stamp_file_config
    BEFORE INSERT OR UPDATE ON tiles
    FOR EACH ROW
    WHEN (NEW.nodegroupid = '@@DATA_FILE_NODEGROUP@@'::uuid)
    EXECUTE FUNCTION ms_xy_stamp_file_config();
