"""
ARCHES - a program developed to inventory and manage immovable cultural heritage.
Copyright (C) 2013 J. Paul Getty Trust and World Monuments Fund

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.
"""

import os
import sys
import inspect

path = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))

if path not in sys.path:
    sys.path.append(path)

# reverting back to the old style of setting the DJANGO_SETTINGS_MODULE env variable
# refer to the following blog post under the heading "Leaking of process environment variables."
# http://blog.dscpl.com.au/2012/10/requests-running-in-wrong-django.html
os.environ["DJANGO_SETTINGS_MODULE"] = "manuspectrum.settings"

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()

from arches.app.models.system_settings import settings

settings.update_from_db()

# update_from_db() ran its queries on the thread importing this module. Under
# the sync worker that thread serves the requests, so close_old_connections()
# recycles the connection at the first request; under gthread (or --preload)
# it never does: the worker's main thread (or the master) serves no request,
# so the connection would stay open, idle, for the life of the process, and a
# preloaded one would be inherited by every forked worker. Close it here.
from django.db import connections

connections.close_all()
