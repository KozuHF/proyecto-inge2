#!/usr/bin/env python
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
sys.path.insert(0, 'C:\\Users\\Forte\\Desktop\\proyecto-inge2')
django.setup()

from django.test.utils import get_runner
from django.conf import settings

TestRunner = get_runner(settings)
test_runner = TestRunner(verbosity=2)

failures = test_runner.run_tests(['apps.pagos.tests.RegistrarPagoEfectivoTestCase'])
sys.exit(bool(failures))
