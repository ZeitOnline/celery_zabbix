from greplin import scales
import celery_zabbix
import celery_zabbix.conftest
import threading


def test_collects_task_events(celery_worker):
    receiver = celery_zabbix.Receiver(celery_zabbix.conftest.CELERY)
    # X + task started + task succeeded
    thread = threading.Thread(target=lambda: receiver(limit=3))
    thread.start()
    celery_zabbix.conftest.celery_ping.delay().get()
    thread.join()
    assert scales.getStats()['celery'].get('succeeded') == 1
