"""Use only with the production entry point and explicitly configured ingress."""

import os

from deploy.runtime import gunicorn_options

globals().update(gunicorn_options(os.environ))
