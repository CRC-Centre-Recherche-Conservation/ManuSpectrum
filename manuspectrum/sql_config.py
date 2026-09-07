"""SQL objects this project owns, versioned through migrations.

``django_migrate_sql`` (the package that supplies ``makemigrations`` here, and
that Arches uses for its own SQL functions) reads ``sql_items`` from this
module. Editing a ``.sql`` body, or a constant substituted into one, makes
``makemigrations`` emit an ``AlterSQL`` migration; ``migrate`` then re-creates
the object. The forward SQL is written to be re-runnable for that reason.

Bodies live in ``manuspectrum/sql/triggers/``. Graph coordinates and the
technique map are substituted as ``@@TOKEN@@`` placeholders, so the ``.sql``
files never repeat a value that :mod:`manuspectrum.constants.xy_presets` owns.
"""

import re
from pathlib import Path

from django.conf import settings
from django_migrate_sql.config import SQLItem

from manuspectrum.constants.xy_presets import (
    DATA_FILE_NODE_ID,
    DATA_FILE_NODEGROUP_ID,
    TECHNIQUE_CONFIG_IDS,
    TECHNIQUE_NODE_ID,
    TECHNIQUE_NODEGROUP_ID,
)

SQL_DIR = Path(__file__).resolve().parent / "sql" / "triggers"


def read_sql(filename, **tokens):
    """Return a ``.sql`` file with every ``@@TOKEN@@`` substituted.

    A placeholder left unresolved raises, since PL/pgSQL would only notice it
    at run time, as a trigger that never matches.
    """
    sql = (SQL_DIR / filename).read_text(encoding="utf-8")
    for name, value in tokens.items():
        sql = sql.replace(f"@@{name}@@", str(value))
    leftover = re.search(r"@@[A-Z0-9_]+@@", sql)
    if leftover:
        raise ValueError(f"{filename} still holds {leftover.group()}")
    return sql


def drop_trigger_sql(name):
    return f"DROP TRIGGER IF EXISTS {name} ON tiles; DROP FUNCTION IF EXISTS {name}();"


sql_items = [
    SQLItem(
        "ms_xy_stamp_file_config",
        read_sql(
            "xy_stamp_file_config.sql",
            DATA_FILE_NODEGROUP=DATA_FILE_NODEGROUP_ID,
            DATA_FILE_NODE=DATA_FILE_NODE_ID,
            TECHNIQUE_NODEGROUP=TECHNIQUE_NODEGROUP_ID,
            TECHNIQUE_NODE=TECHNIQUE_NODE_ID,
            TEXT_FORMATS=", ".join(
                f"'{extension}'" for extension in settings.XY_TEXT_FILE_FORMATS
            ),
            TECHNIQUE_MAP=",\n        ".join(
                f"('{item_id}', '{config_id}'::uuid)"
                for item_id, config_id in TECHNIQUE_CONFIG_IDS.items()
            ),
        ),
        reverse_sql=drop_trigger_sql("ms_xy_stamp_file_config"),
        replace=True,
    ),
    SQLItem(
        "ms_xy_reapply_on_technique",
        read_sql(
            "xy_reapply_on_technique.sql",
            DATA_FILE_NODEGROUP=DATA_FILE_NODEGROUP_ID,
            TECHNIQUE_NODEGROUP=TECHNIQUE_NODEGROUP_ID,
        ),
        reverse_sql=drop_trigger_sql("ms_xy_reapply_on_technique"),
        replace=True,
    ),
]
