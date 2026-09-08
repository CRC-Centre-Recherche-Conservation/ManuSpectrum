-- Re-touch the measurement file tiles of an analysis whose technique was just
-- written, so that `ms_xy_stamp_file_config` runs over them again: files are
-- uploaded before and after the technique is tagged, and the stamp has to
-- converge from either order. Fires for the technique nodegroup only and
-- touches file-nodegroup rows only, so it cannot recurse.

CREATE OR REPLACE FUNCTION ms_xy_reapply_on_technique() RETURNS trigger
LANGUAGE plpgsql AS $body$
BEGIN
    UPDATE tiles
    SET tiledata = tiledata
    WHERE nodegroupid = '@@DATA_FILE_NODEGROUP@@'::uuid
      AND resourceinstanceid = NEW.resourceinstanceid;

    RETURN NEW;
END
$body$;

DROP TRIGGER IF EXISTS ms_xy_reapply_on_technique ON tiles;
CREATE TRIGGER ms_xy_reapply_on_technique
    AFTER INSERT OR UPDATE ON tiles
    FOR EACH ROW
    WHEN (NEW.nodegroupid = '@@TECHNIQUE_NODEGROUP@@'::uuid)
    EXECUTE FUNCTION ms_xy_reapply_on_technique();
