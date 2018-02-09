import celery
import celery.contrib.testing.app
import pytest


CELERY = celery.Celery()


@pytest.fixture(scope='session')
def celery_worker(request):
    CELERY.conf.update(celery.contrib.testing.app.DEFAULT_TEST_CONFIG)
    CELERY.conf['worker_send_task_events'] = True
    worker = celery.contrib.testing.worker.start_worker(CELERY)
    worker.__enter__()
    request.addfinalizer(lambda: worker.__exit__(None, None, None))


# celery.contrib.testing.worker expects a 'ping' task, so it can check that the
# worker is running properly.
@CELERY.task(name='celery.ping')
def celery_ping():
    return 'pong'
